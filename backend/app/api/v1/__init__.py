from flask import Blueprint
from app.api.v1.health import health_bp
from app.api.v1.auth import auth_bp
from app.api.v1.organizations import org_bp
from app.api.v1.sites import sites_bp
from app.api.v1.users import users_bp
from app.modules.equipment import equipment_bp, areas_bp, lines_bp
from app.modules.connectivity import connectivity_bp
from app.modules.connectivity.routes import connectors_bp
from app.modules.signal_mapping.routes import signals_bp
from app.modules.monitoring.routes import monitoring_bp
from app.modules.data_quality.routes import data_quality_bp
from app.modules.operating_context.routes import operating_context_bp
from app.modules.baselines.routes import baselines_bp
from app.modules.anomalies.routes import anomalies_bp
from app.modules.alerts.routes import alerts_bp
from app.modules.condition_monitoring.routes import condition_monitoring_bp
from app.modules.predictions.routes import predictions_bp
from app.modules.diagnostics import diagnostics_bp
from app.modules.maintenance_recommendations import recommendations_bp
from app.modules.knowledge import knowledge_bp
from app.modules.pilots.routes import pilots_bp
from app.modules.signal_mapping.commissioning_routes import commissioning_bp

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

api_v1_bp.register_blueprint(health_bp)
api_v1_bp.register_blueprint(auth_bp)
api_v1_bp.register_blueprint(org_bp)
api_v1_bp.register_blueprint(sites_bp)
api_v1_bp.register_blueprint(users_bp)
api_v1_bp.register_blueprint(equipment_bp)
api_v1_bp.register_blueprint(areas_bp)
api_v1_bp.register_blueprint(lines_bp)
api_v1_bp.register_blueprint(connectivity_bp)
api_v1_bp.register_blueprint(connectors_bp)
api_v1_bp.register_blueprint(signals_bp)
api_v1_bp.register_blueprint(monitoring_bp)
api_v1_bp.register_blueprint(data_quality_bp)
api_v1_bp.register_blueprint(operating_context_bp)
api_v1_bp.register_blueprint(baselines_bp)
api_v1_bp.register_blueprint(anomalies_bp)
api_v1_bp.register_blueprint(alerts_bp)
api_v1_bp.register_blueprint(condition_monitoring_bp)
api_v1_bp.register_blueprint(predictions_bp)
api_v1_bp.register_blueprint(diagnostics_bp)
api_v1_bp.register_blueprint(recommendations_bp)
api_v1_bp.register_blueprint(knowledge_bp)
api_v1_bp.register_blueprint(pilots_bp)
api_v1_bp.register_blueprint(commissioning_bp)
