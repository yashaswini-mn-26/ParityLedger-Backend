from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager

from config import Config
from extensions import init_db


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    CORS(app, resources={r"/api/*": {"origins": Config.CORS_ORIGINS}}, supports_credentials=True)
    JWTManager(app)
    init_db()

    from routes.auth_routes import bp as auth_bp
    from routes.project_routes import bp as project_bp
    from routes.folder_routes import bp as folder_bp
    from routes.page_routes import bp as page_bp
    from routes.search_routes import bp as search_bp
    from routes.export_routes import bp as export_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(project_bp)
    app.register_blueprint(folder_bp)
    app.register_blueprint(page_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(export_bp)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"})

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(413)
    def too_large(e):
        return jsonify({"error": "Request payload too large"}), 413

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": "Internal server error"}), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=Config.PORT, debug=Config.DEBUG)
