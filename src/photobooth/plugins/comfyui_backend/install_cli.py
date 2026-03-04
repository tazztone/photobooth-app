import argparse
import logging
import time

from .config import ComfyuiBackendConfig
from .server_manager import ServerManager

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="ComfyUI Backend Installer and Manager")
    parser.add_argument("--install", action="store_true", help="Install/Update ComfyUI and models (default if no other args)")
    parser.add_argument("--start", action="store_true", help="Start the managed ComfyUI server")

    args = parser.parse_args()
    config = ComfyuiBackendConfig()
    manager = ServerManager(config.server_path)

    # If no args provided, default to install
    if not args.start and not args.install:
        args.install = True

    if args.install:
        logger.info("==================================================")
        logger.info("Installing ComfyUI and required models for Photobooth")
        logger.info(f"Target directory: {config.server_path.absolute()}")
        logger.info("==================================================")

        try:
            manager.install()

            # Intent is clear from running the command - ensure managed_server is enabled for boot
            if not config.manage_server:
                logger.info("Enabling 'manage_server' in plugin configuration...")
                config.manage_server = True
                config.persist()

            logger.info("\n✅ Installation complete and enabled!")
        except Exception as e:
            logger.error(f"\n❌ Installation failed: {e}")
            raise

    if args.start:
        if not manager.is_installed():
            logger.error("Error: ComfyUI is not installed. Run with --install first.")
            return

        logger.info("==================================================")
        logger.info("Starting Managed ComfyUI Server")
        logger.info(f"Host: {config.comfyui_host}")
        logger.info("Press Ctrl+C to stop")
        logger.info("==================================================")

        try:
            manager.start(host=config.comfyui_host)
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\nStopping server...")
            manager.stop()
        except Exception as e:
            logger.error(f"Error: {e}")
            manager.stop()
            raise


if __name__ == "__main__":
    main()
