"""Azure Functions entry point — registers all blueprints."""

import azure.functions as func

from blueprints.analysis import bp as analysis_bp
from blueprints.contact import bp as contact_bp
from blueprints.demo import bp as demo_bp
from blueprints.health import bp as health_bp
from blueprints.pipeline import bp as pipeline_bp
from treesight.config import validate_config

# Fail-fast config validation (§8.6)
validate_config()

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Register HTTP blueprints
app.register_functions(health_bp)
app.register_functions(contact_bp)
app.register_functions(demo_bp)
app.register_functions(analysis_bp)

# Register durable pipeline blueprint
app.register_functions(pipeline_bp)
