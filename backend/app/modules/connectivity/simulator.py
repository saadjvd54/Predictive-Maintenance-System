import os
import asyncio
import logging
from typing import Optional, Dict
from datetime import datetime, timezone
import asyncua
from asyncua import Server, ua
from asyncua.server.user_managers import UserManager, User, UserRole

from app.modules.connectivity.security import generate_self_signed_cert, compute_cert_fingerprint

logger = logging.getLogger(__name__)


class PharmaUserManager(UserManager):
    """User manager verifying credentials against configured pharmaceutical operator logins."""
    def __init__(self, valid_users: Dict[str, str], allow_anonymous: bool = True):
        self.valid_users = valid_users
        self.allow_anonymous = allow_anonymous

    def get_user(self, iserver, username=None, password=None, certificate=None):
        if username is None and self.allow_anonymous:
            return User(role=UserRole.User, name="Anonymous")
        if username in self.valid_users and self.valid_users[username] == password:
            return User(role=UserRole.User, name=username)
        # Authentication failure: wrong user or password
        return None


class PharmaOPCUASimulator:
    """Industrial OPC UA simulator server for pharmaceutical machinery.
    
    Provides simulated nodes for blister packaging and tablet compression machinery,
    and supports security policies (Anonymous, UserName/Password, X.509 Certificate Handshake).
    Never connects to real production equipment (Requirement 13).
    """

    def __init__(
        self,
        port: int = 48401,
        enable_security: bool = False,
        cert_dir: Optional[str] = None,
        valid_users: Optional[Dict[str, str]] = None,
    ):
        self.port = port
        self.enable_security = enable_security
        self.cert_dir = cert_dir or os.path.join(os.path.dirname(__file__), ".certs")
        self.valid_users = valid_users or {"operator": "PharmaSecure123!"}
        self.server: Optional[Server] = None
        self.endpoint_url = f"opc.tcp://127.0.0.1:{self.port}/pharmapredict/server/"
        self.cert_path: Optional[str] = None
        self.key_path: Optional[str] = None
        self._server_cert_der: Optional[bytes] = None

        # Node references for simulated telemetry
        self.blister_speed_node = None
        self.blister_rpm_node = None
        self.blister_temp_node = None
        self.blister_motor_temp_node = None
        self.blister_vibration_node = None
        self.blister_bearing_vib_node = None
        self.blister_motor_curr_node = None
        self.blister_vacuum_node = None
        self.blister_forming_press_node = None
        self.blister_fault_alarm_node = None
        self.blister_estop_node = None
        self.blister_cycle_count_node = None
        self.blister_batch_count_node = None

    async def start(self) -> None:
        """Initialize and start the OPC UA server."""
        self.server = Server()
        await self.server.init()
        self.server.set_endpoint(self.endpoint_url)
        self.server.set_server_name("PharmaPredict Pharmaceutical Machine Simulator")

        # Configure Security if requested
        if self.enable_security:
            self.cert_path, self.key_path = generate_self_signed_cert(
                output_dir=self.cert_dir,
                common_name="PharmaPredict-Simulator-Server"
            )
            await self.server.load_certificate(self.cert_path)
            await self.server.load_private_key(self.key_path)

            with open(self.cert_path, "rb") as f:
                cert_pem = f.read()
                from cryptography import x509
                from cryptography.hazmat.primitives import serialization
                c = x509.load_pem_x509_certificate(cert_pem)
                self._server_cert_der = c.public_bytes(serialization.Encoding.DER)

            self.server.set_security_policy([
                ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
                ua.SecurityPolicyType.Basic256Sha256_Sign,
                ua.SecurityPolicyType.NoSecurity,
            ])

        # Configure User Authentication
        if self.valid_users:
            self.server.iserver.set_user_manager(PharmaUserManager(self.valid_users))

        # Build pharmaceutical namespace and nodes
        uri = "http://pharmapredict.ai/packaging/"
        idx = await self.server.register_namespace(uri)

        # Create Machine Object in Address Space with explicit NodeId
        objects = self.server.nodes.objects
        blister_machine = await objects.add_object(
            ua.NodeId("BlisterPackagingMachine_01", idx),
            "BlisterPackagingMachine_01"
        )

        # Create All 13 Critical Sensor and Metric Nodes with explicit string NodeIds
        self.blister_speed_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.Speed_CPM", idx),
            "Speed_CPM", 240.0, ua.VariantType.Double
        )
        self.blister_rpm_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.MachineSpeedRPM", idx),
            "MachineSpeedRPM", 1450.0, ua.VariantType.Double
        )
        self.blister_temp_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.SealingTemperature", idx),
            "SealingTemperature", 142.5, ua.VariantType.Double
        )
        self.blister_motor_temp_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.MotorTemperature", idx),
            "MotorTemperature", 65.2, ua.VariantType.Double
        )
        self.blister_vibration_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.MainDriveMotorVibration", idx),
            "MainDriveMotorVibration", 1.25, ua.VariantType.Double
        )
        self.blister_bearing_vib_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.BearingVibration", idx),
            "BearingVibration", 0.42, ua.VariantType.Double
        )
        self.blister_motor_curr_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.MainDriveMotorCurrent", idx),
            "MainDriveMotorCurrent", 14.8, ua.VariantType.Double
        )
        self.blister_vacuum_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.VacuumLevel", idx),
            "VacuumLevel", -85.2, ua.VariantType.Double
        )
        self.blister_forming_press_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.FormingAirPressure", idx),
            "FormingAirPressure", 6.2, ua.VariantType.Double
        )
        self.blister_fault_alarm_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.MachineFaultAlarm", idx),
            "MachineFaultAlarm", False, ua.VariantType.Boolean
        )
        self.blister_estop_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.EmergencyStopActive", idx),
            "EmergencyStopActive", False, ua.VariantType.Boolean
        )
        self.blister_cycle_count_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.CumulativeCycleCount", idx),
            "CumulativeCycleCount", 125430, ua.VariantType.Int32
        )
        self.blister_batch_count_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.BatchProductionCount", idx),
            "BatchProductionCount", 4520, ua.VariantType.Int32
        )

        # Set read-only permissions for all 13 variables
        all_nodes = [
            self.blister_speed_node,
            self.blister_rpm_node,
            self.blister_temp_node,
            self.blister_motor_temp_node,
            self.blister_vibration_node,
            self.blister_bearing_vib_node,
            self.blister_motor_curr_node,
            self.blister_vacuum_node,
            self.blister_forming_press_node,
            self.blister_fault_alarm_node,
            self.blister_estop_node,
            self.blister_cycle_count_node,
            self.blister_batch_count_node,
        ]
        for node in all_nodes:
            await node.set_read_only()

        await self.server.start()
        logger.info(f"PharmaPredict OPC UA Simulator started at {self.endpoint_url}")

    async def stop(self) -> None:
        """Stop the OPC UA server and release the network port."""
        if self.server:
            try:
                await self.server.stop()
            except Exception:
                pass
            finally:
                self.server = None

    def get_endpoint(self) -> str:
        return self.endpoint_url

    def get_server_certificate_der(self) -> Optional[bytes]:
        return self._server_cert_der

    def get_server_certificate_fingerprint(self) -> Optional[str]:
        if self._server_cert_der:
            return compute_cert_fingerprint(self._server_cert_der)
        return None

    async def apply_scenario(self, scenario: str) -> None:
        """Applies deterministic scenario values to simulated OPC UA nodes."""
        scenario = scenario.upper()
        if not self.server:
            return

        if scenario == "NORMAL_OPERATION":
            if self.blister_speed_node:
                await self.blister_speed_node.write_value(240.0)
            if self.blister_temp_node:
                await self.blister_temp_node.write_value(142.5)
            if self.blister_vibration_node:
                await self.blister_vibration_node.write_value(1.25)
            if self.blister_vacuum_node:
                await self.blister_vacuum_node.write_value(-85.2)
        elif scenario == "ABNORMAL_VIBRATION":
            if self.blister_vibration_node:
                await self.blister_vibration_node.write_value(4.95)
        elif scenario == "OVERHEATING":
            if self.blister_temp_node:
                await self.blister_temp_node.write_value(178.5)
        elif scenario == "MACHINE_IDLE":
            if self.blister_speed_node:
                await self.blister_speed_node.write_value(0.0)
            if self.blister_temp_node:
                await self.blister_temp_node.write_value(24.0)
            if self.blister_vibration_node:
                await self.blister_vibration_node.write_value(0.05)
        elif scenario == "SENSOR_FAILURE":
            if self.blister_vacuum_node:
                await self.blister_vacuum_node.write_value(float("nan"))


