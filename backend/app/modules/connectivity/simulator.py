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
        enable_dynamic_simulation: bool = False,
        cert_dir: Optional[str] = None,
        valid_users: Optional[Dict[str, str]] = None,
    ):
        self.port = port
        self.enable_security = enable_security
        self.enable_dynamic_simulation = enable_dynamic_simulation
        self.cert_dir = cert_dir or os.path.join(os.path.dirname(__file__), ".certs")
        self.valid_users = valid_users or {"operator": "PharmaSecure123!"}
        self.server: Optional[Server] = None
        self.endpoint_url = f"opc.tcp://127.0.0.1:{self.port}/pharmapredict/server/"
        self.cert_path: Optional[str] = None
        self.key_path: Optional[str] = None
        self._server_cert_der: Optional[bytes] = None

        # Node references for simulated telemetry across all 7 industrial categories
        self.blister_speed_node = None
        self.blister_rpm_node = None
        self.blister_temp_node = None
        self.blister_motor_temp_node = None
        self.blister_vibration_node = None
        self.blister_bearing_vib_node = None
        self.blister_current_node = None
        self.blister_vacuum_node = None
        self.blister_pressure_node = None
        self.blister_alarm_node = None
        self.blister_estop_node = None
        self.blister_cycle_node = None
        self.blister_production_count_node = None
        
        self._simulation_task: Optional[asyncio.Task] = None
        self._is_running: bool = False

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

        # Create Machine Object in Address Space
        objects = self.server.nodes.objects
        blister_machine = await objects.add_object(idx, "BlisterPackagingMachine_01")

        # Create Critical Sensor Nodes across all 7 industrial categories (Requirement 3)
        # 1. Speed & RPM
        self.blister_speed_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.Speed_CPM", idx), "Speed_CPM", 240.0, ua.VariantType.Double
        )
        self.blister_rpm_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.MachineSpeedRPM", idx), "MachineSpeedRPM", 1440.0, ua.VariantType.Double
        )
        # 2. Temperature (Sealing & Motor)
        self.blister_temp_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.SealingTemperature", idx), "SealingTemperature", 142.5, ua.VariantType.Double
        )
        self.blister_motor_temp_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.MotorTemperature", idx), "MotorTemperature", 52.4, ua.VariantType.Double
        )
        # 3. Vibration (Overall & Bearing)
        self.blister_vibration_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.MainDriveMotorVibration", idx), "MainDriveMotorVibration", 1.25, ua.VariantType.Double
        )
        self.blister_bearing_vib_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.BearingVibration", idx), "BearingVibration", 0.85, ua.VariantType.Double
        )
        # 4. Motor Current
        self.blister_current_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.MainDriveMotorCurrent", idx), "MainDriveMotorCurrent", 14.8, ua.VariantType.Double
        )
        # 5. Pressure (Vacuum & Pneumatic)
        self.blister_vacuum_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.VacuumLevel", idx), "VacuumLevel", -0.85, ua.VariantType.Double
        )
        self.blister_pressure_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.FormingAirPressure", idx), "FormingAirPressure", 6.2, ua.VariantType.Double
        )
        # 6. Alarms & Safety
        self.blister_alarm_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.MachineFaultAlarm", idx), "MachineFaultAlarm", False, ua.VariantType.Boolean
        )
        self.blister_estop_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.EmergencyStopActive", idx), "EmergencyStopActive", False, ua.VariantType.Boolean
        )
        # 7. Cycles & Production Count
        self.blister_cycle_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.CumulativeCycleCount", idx), "CumulativeCycleCount", 128450, ua.VariantType.Int32
        )
        self.blister_production_count_node = await blister_machine.add_variable(
            ua.NodeId("BlisterPackagingMachine_01.BatchProductionCount", idx), "BatchProductionCount", 1420, ua.VariantType.Int32
        )

        # Set read permissions for all variables (Strict read-only safety)
        all_sim_nodes = [
            self.blister_speed_node,
            self.blister_rpm_node,
            self.blister_temp_node,
            self.blister_motor_temp_node,
            self.blister_vibration_node,
            self.blister_bearing_vib_node,
            self.blister_current_node,
            self.blister_vacuum_node,
            self.blister_pressure_node,
            self.blister_alarm_node,
            self.blister_estop_node,
            self.blister_cycle_node,
            self.blister_production_count_node,
        ]
        for node in all_sim_nodes:
            if node:
                await node.set_read_only()

        await self.server.start()
        self._is_running = True
        if self.enable_dynamic_simulation:
            self._simulation_task = asyncio.create_task(self._simulation_loop())
        logger.info(f"PharmaPredict OPC UA Simulator started at {self.endpoint_url} with 13 industrial sensor nodes.")

    async def _simulation_loop(self) -> None:
        """Periodically update sensor values with realistic industrial fluctuations."""
        import math
        import random
        t = 0.0
        while self._is_running:
            try:
                await asyncio.sleep(1.0)
                t += 1.0
                if not self.server:
                    break

                # Dynamic subtle fluctuations
                temp_val = 142.5 + 0.8 * math.sin(t / 10.0) + random.uniform(-0.1, 0.1)
                motor_temp = 52.4 + 0.5 * math.sin(t / 15.0) + random.uniform(-0.05, 0.05)
                vib_val = 1.25 + 0.15 * math.sin(t / 5.0) + random.uniform(-0.02, 0.02)
                bearing_vib = 0.85 + 0.1 * math.sin(t / 4.0) + random.uniform(-0.02, 0.02)
                curr_val = 14.8 + 0.4 * math.cos(t / 8.0) + random.uniform(-0.05, 0.05)
                rpm_val = 1440.0 + 5.0 * math.sin(t / 7.0)
                vac_val = -0.85 + 0.02 * math.cos(t / 6.0)

                if self.blister_temp_node:
                    await self.blister_temp_node.write_value(round(temp_val, 2))
                if self.blister_motor_temp_node:
                    await self.blister_motor_temp_node.write_value(round(motor_temp, 2))
                if self.blister_vibration_node:
                    await self.blister_vibration_node.write_value(round(vib_val, 3))
                if self.blister_bearing_vib_node:
                    await self.blister_bearing_vib_node.write_value(round(bearing_vib, 3))
                if self.blister_current_node:
                    await self.blister_current_node.write_value(round(curr_val, 2))
                if self.blister_rpm_node:
                    await self.blister_rpm_node.write_value(round(rpm_val, 1))
                if self.blister_vacuum_node:
                    await self.blister_vacuum_node.write_value(round(vac_val, 3))
                if self.blister_cycle_node and int(t) % 2 == 0:
                    curr_c = await self.blister_cycle_node.read_value()
                    await self.blister_cycle_node.write_value(curr_c + 1)
                if self.blister_production_count_node and int(t) % 4 == 0:
                    curr_p = await self.blister_production_count_node.read_value()
                    await self.blister_production_count_node.write_value(curr_p + 1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[Simulator] Dynamic tick error: {e}")

    async def stop(self) -> None:
        """Stop the OPC UA server, cancel simulation tasks, and release network port."""
        self._is_running = False
        if self._simulation_task and not self._simulation_task.done():
            self._simulation_task.cancel()
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


