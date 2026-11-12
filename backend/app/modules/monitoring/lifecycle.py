import asyncio
import logging
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timezone

from app.extensions import db
from app.models.equipment import Machine
from app.models.signal_mapping import MachineSignal, ValidationStatus
from app.models.monitoring import (
    MonitoringSession,
    SubscriptionStatus,
    GatewayHealthRecord,
    MonitoringState,
)
from app.modules.connectivity.models import ConnectionState, ConnectionConfig, UserAuthType
from app.modules.connectivity.connection_manager import (
    ConnectionLifecycleManager,
    GatewayManager,
)
from app.modules.monitoring.gateway_buffer import BoundedGatewayBuffer
from app.modules.monitoring.opcua_subscription import OPCUASubscriptionService
from app.modules.monitoring.ingestion_service import IngestionService

logger = logging.getLogger(__name__)


class ActiveMachinePipeline:
    """Holds active in-memory subscription service and buffer for a running machine monitoring session."""
    def __init__(
        self,
        machine_id: str,
        manager: ConnectionLifecycleManager,
        buffer: BoundedGatewayBuffer,
        subscription_service: OPCUASubscriptionService,
    ):
        self.machine_id = machine_id
        self.manager = manager
        self.buffer = buffer
        self.subscription_service = subscription_service


class MonitoringLifecycleManager:
    """Manages the full lifecycle of industrial machine monitoring:
    - Precondition validation
    - Idempotent activation & deactivation
    - Desired state vs observed state separation
    - Gateway subscription orchestration
    """

    _pipelines: Dict[str, ActiveMachinePipeline] = {}

    @classmethod
    def clean_all(cls):
        """Cancel and stop all active monitoring pipelines and gateway connections."""
        pipelines = list(cls._pipelines.values())
        cls._pipelines.clear()
        for p in pipelines:
            try:
                if p.manager and p.manager._loop and p.manager._loop.is_running():
                    async def _stop(pipe=p):
                        try:
                            await pipe.subscription_service.unsubscribe_all()
                        except Exception:
                            pass
                        try:
                            await pipe.buffer.stop()
                        except Exception:
                            pass
                    fut = asyncio.run_coroutine_threadsafe(_stop(), p.manager._loop)
                    try:
                        fut.result(timeout=2.0)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Error cleaning pipeline {p.machine_id}: {e}")

    @classmethod
    def get_pipeline(cls, machine_id: str) -> Optional[ActiveMachinePipeline]:
        return cls._pipelines.get(machine_id)

    @classmethod
    def check_activation_preconditions(
        cls, machine_id: str, organization_id: str
    ) -> Tuple[bool, str, List[MachineSignal]]:
        """Verify all mandatory activation preconditions before engaging monitoring."""
        machine = db.session.get(Machine, machine_id)
        if not machine or machine.organization_id != organization_id:
            return False, "Equipment asset not found or access denied.", []

        signals = MachineSignal.query.filter_by(
            machine_id=machine_id,
            organization_id=organization_id,
            enabled=True,
        ).all()

        if not signals:
            return False, "No active signal mappings configured for this equipment.", []

        # Check for unresolved invalid configurations
        invalid_signals = [s for s in signals if s.validation_status == ValidationStatus.INVALID]
        if invalid_signals:
            names = [s.custom_name or s.source_node_id for s in invalid_signals]
            return False, f"Cannot activate: {len(invalid_signals)} signal(s) have invalid configurations: {', '.join(names)}.", signals

        return True, "All preconditions verified. Machine ready for monitoring activation.", signals

    @classmethod
    def activate_monitoring(
        cls,
        machine_id: str,
        organization_id: str,
        user_id: Optional[str] = None,
        endpoint_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Activate continuous monitoring for a machine."""
        can_activate, reason, signals = cls.check_activation_preconditions(machine_id, organization_id)
        if not can_activate:
            raise ValueError(reason)

        machine = db.session.get(Machine, machine_id)

        # 1. Record or update session with DESIRED=ACTIVE, OBSERVED=ACTIVATING
        session = (
            MonitoringSession.query.filter_by(machine_id=machine_id, organization_id=organization_id)
            .order_by(MonitoringSession.created_at.desc())
            .first()
        )

        if not session or session.observed_state in (MonitoringState.STOPPED, MonitoringState.ERROR):
            session = MonitoringSession(
                organization_id=organization_id,
                machine_id=machine_id,
                requested_by=user_id,
                desired_state=MonitoringState.ACTIVE,
                observed_state=MonitoringState.ACTIVATING,
                status_reason="Monitoring activation requested by user.",
                mapping_version=signals[0].mapping_version if signals else 1,
            )
            db.session.add(session)
        else:
            session.desired_state = MonitoringState.ACTIVE
            session.observed_state = MonitoringState.ACTIVATING
            session.status_reason = "Re-activating monitoring session."

        db.session.commit()

        from flask import current_app
        app = current_app._get_current_object()
        session_id = session.id

        # 2. Get or initialize ConnectionLifecycleManager
        manager = GatewayManager.get(machine_id)
        target_url = endpoint_url or "opc.tcp://127.0.0.1:48401/pharmapredict/server/"

        if not manager:
            config = ConnectionConfig(
                endpoint_url=target_url,
                timeout_sec=3.5,
                user_auth_type=UserAuthType.ANONYMOUS,
                auto_trust_unknown=True,
            )
            manager = ConnectionLifecycleManager(config, machine_id=machine_id)
            manager.start_background_worker()
            GatewayManager.register(machine_id, manager)

        # 3. Create bounded buffer wired to internal ingestion
        buffer = BoundedGatewayBuffer(gateway_id=f"gw-{machine_id[:8]}")

        # Ingestion callback
        def _on_batch_flush(batch_items):
            # Run batch ingestion in Flask app context
            with app.app_context():
                dict_items = [b.to_dict() for b in batch_items]
                return IngestionService.ingest_batch(
                    gateway_id=buffer.gateway_id,
                    readings_data=dict_items,
                )

        buffer.set_ingestion_handler(_on_batch_flush)

        # 4. Asynchronously connect and establish subscriptions on background thread
        sub_service = OPCUASubscriptionService(manager.client, buffer)
        pipeline = ActiveMachinePipeline(machine_id, manager, buffer, sub_service)
        cls._pipelines[machine_id] = pipeline

        # Execute connection & subscription in worker thread
        async def _do_activation():
            try:
                # 1. Start buffer flush loop
                await buffer.start()

                # 2. Connect if not connected
                if not manager.client.is_connected():
                    await manager.client.connect()

                # 3. Subscribe to each signal
                subscribed_items = []
                failed_items = []
                for sig in signals:
                    try:
                        res = await sub_service.subscribe_signal(sig)
                        subscribed_items.append((sig.id, res["subscription_id"], res["revised_sampling_interval"]))
                    except Exception as sub_err:
                        logger.error(f"Subscription failed for signal {sig.id}: {sub_err}")
                        failed_items.append((sig.id, str(sub_err)))

                # 4. Save subscription records and update status in clean app_context
                with app.app_context():
                    s = db.session.get(MonitoringSession, session_id)
                    m = db.session.get(Machine, machine_id)

                    for sig_id, sub_ident, rev_interval in subscribed_items:
                        db.session.add(SubscriptionStatus(
                            monitoring_session_id=s.id if s else None,
                            signal_id=sig_id,
                            subscription_identifier=sub_ident,
                            status="SUBSCRIBED",
                            revised_sampling_interval=rev_interval,
                        ))

                    for sig_id, err_str in failed_items:
                        db.session.add(SubscriptionStatus(
                            monitoring_session_id=s.id if s else None,
                            signal_id=sig_id,
                            status="FAILED",
                            last_error=err_str,
                        ))

                    if s:
                        if len(subscribed_items) == len(signals):
                            s.observed_state = MonitoringState.ACTIVE
                            s.status_reason = f"Monitoring active with {len(subscribed_items)} confirmed subscriptions."
                            s.activated_at = datetime.now(timezone.utc)
                            if m:
                                m.monitoring_status = "Active"
                        elif len(subscribed_items) > 0:
                            s.observed_state = MonitoringState.DEGRADED
                            s.status_reason = f"Degraded monitoring: {len(subscribed_items)}/{len(signals)} subscriptions confirmed."
                            s.activated_at = datetime.now(timezone.utc)
                            if m:
                                m.monitoring_status = "Active"
                        else:
                            s.observed_state = MonitoringState.ERROR
                            s.status_reason = "Failed to establish any signal subscriptions."
                            if m:
                                m.monitoring_status = "Error"

                    db.session.commit()
            except Exception as e:
                logger.error(f"[MonitoringLifecycle] Activation error for machine {machine_id}: {e}")
                try:
                    with app.app_context():
                        s = db.session.get(MonitoringSession, session_id)
                        m = db.session.get(Machine, machine_id)
                        if s:
                            s.observed_state = MonitoringState.ERROR
                            s.status_reason = f"Activation failed: {e}"
                        if m:
                            m.monitoring_status = "Error"
                        db.session.commit()
                except Exception:
                    pass

        # Run on worker loop
        if manager._loop and manager._loop.is_running():
            asyncio.run_coroutine_threadsafe(_do_activation(), manager._loop)
        else:
            asyncio.run(_do_activation())

        return session.to_dict()

    @classmethod
    def deactivate_monitoring(
        cls, machine_id: str, organization_id: str, user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Deactivate monitoring gracefully."""
        from flask import current_app
        app = current_app._get_current_object()

        machine = db.session.get(Machine, machine_id)
        if not machine or machine.organization_id != organization_id:
            raise ValueError("Equipment asset not found or access denied.")

        session = (
            MonitoringSession.query.filter_by(machine_id=machine_id, organization_id=organization_id)
            .order_by(MonitoringSession.created_at.desc())
            .first()
        )

        if not session or session.observed_state == MonitoringState.STOPPED:
            return {"message": "Monitoring is already stopped.", "machine_id": machine_id}

        session_id = session.id
        session.desired_state = MonitoringState.STOPPED
        session.observed_state = MonitoringState.STOPPING
        session.status_reason = "Monitoring deactivation requested by user."
        db.session.commit()

        pipeline = cls._pipelines.pop(machine_id, None)

        async def _do_deactivation():
            try:
                if pipeline:
                    # Cancel subscriptions
                    await pipeline.subscription_service.unsubscribe_all()
                    # Stop buffer and flush remaining
                    await pipeline.buffer.stop()

                with app.app_context():
                    s = db.session.get(MonitoringSession, session_id)
                    m = db.session.get(Machine, machine_id)
                    if s:
                        s.observed_state = MonitoringState.STOPPED
                        s.stopped_at = datetime.now(timezone.utc)
                        s.status_reason = "Monitoring stopped successfully."
                    if m:
                        m.monitoring_status = "Suspended"
                    db.session.commit()
            except Exception as e:
                logger.error(f"[MonitoringLifecycle] Error during deactivation: {e}")
                try:
                    with app.app_context():
                        s = db.session.get(MonitoringSession, session_id)
                        if s:
                            s.observed_state = MonitoringState.ERROR
                            s.status_reason = f"Error stopping monitoring: {e}"
                        db.session.commit()
                except Exception:
                    pass

        manager = GatewayManager.get(machine_id)
        if manager and manager._loop and manager._loop.is_running():
            asyncio.run_coroutine_threadsafe(_do_deactivation(), manager._loop)
        else:
            asyncio.run(_do_deactivation())

        return session.to_dict()

    @classmethod
    def get_status(cls, machine_id: str, organization_id: str) -> Dict[str, Any]:
        """Return real-time monitoring session and gateway health metrics."""
        machine = db.session.get(Machine, machine_id)
        if not machine or machine.organization_id != organization_id:
            raise ValueError("Equipment asset not found or access denied.")

        session = (
            MonitoringSession.query.filter_by(machine_id=machine_id, organization_id=organization_id)
            .order_by(MonitoringSession.created_at.desc())
            .first()
        )

        pipeline = cls.get_pipeline(machine_id)
        active_subscriptions = pipeline.subscription_service.get_active_count() if pipeline else 0
        buffer_metrics = pipeline.buffer.get_metrics() if pipeline else {
            "queue_depth": 0,
            "buffered_readings": 0,
            "dropped_readings": 0,
        }

        # Check preconditions
        can_activate, reason, signals = cls.check_activation_preconditions(machine_id, organization_id)

        observed_state = session.observed_state if session else MonitoringState.STOPPED
        status_reason = session.status_reason if session else None
        simulator_flag = True

        # Check for active external edge gateway telemetry stream (Requirement 2 & 3)
        if not pipeline:
            from app.models.monitoring import SignalReading
            latest_reading = (
                SignalReading.query.filter_by(machine_id=machine_id, organization_id=organization_id)
                .order_by(SignalReading.source_timestamp.desc())
                .first()
            )
            if latest_reading and latest_reading.source_timestamp:
                now_utc = datetime.now(timezone.utc)
                ts = latest_reading.source_timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_sec = (now_utc - ts).total_seconds()
                simulator_flag = latest_reading.simulator_flag

                gw_health = GatewayHealthRecord.query.filter_by(gateway_id=latest_reading.gateway_id).first()
                if gw_health:
                    buffer_metrics = {
                        "queue_depth": gw_health.queue_depth,
                        "buffered_readings": gw_health.buffered_readings,
                        "dropped_readings": gw_health.dropped_readings,
                    }

                if age_sec <= 20.0:
                    observed_state = MonitoringState.ACTIVE
                    status_reason = f"Edge Gateway '{latest_reading.gateway_id}' streaming live telemetry ({round(age_sec, 1)}s ago)."
                    active_subscriptions = len(signals)

        return {
            "machine_id": machine_id,
            "machine_name": machine.equipment_name,
            "desired_state": session.desired_state if session else MonitoringState.STOPPED,
            "observed_state": observed_state,
            "status_reason": status_reason,
            "activated_at": session.activated_at.isoformat() if session and session.activated_at else None,
            "active_subscriptions": active_subscriptions,
            "total_mapped_signals": len(signals),
            "can_activate": can_activate,
            "activation_precondition_reason": reason,
            "buffer_metrics": buffer_metrics,
            "simulator_flag": simulator_flag,
        }
