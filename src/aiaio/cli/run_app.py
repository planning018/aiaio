import os
import signal
import subprocess
import sys
from argparse import ArgumentParser

from aiaio import logger

from . import BaseCLICommand


def run_app_command_factory(args):
    return RunAppCommand(args.port, args.host, args.workers)


class RunAppCommand(BaseCLICommand):
    @staticmethod
    def register_subcommand(parser: ArgumentParser):
        run_app_parser = parser.add_parser(
            "app",
            description="✨ Run app",
        )
        run_app_parser.add_argument(
            "--port",
            type=int,
            default=10000,
            help="Port to run the app on",
            required=False,
        )
        run_app_parser.add_argument(
            "--host",
            type=str,
            default="127.0.0.1",
            help="Host to run the app on",
            required=False,
        )
        run_app_parser.add_argument(
            "--workers",
            type=int,
            default=1,
            help="Number of workers to run the app with",
            required=False,
        )
        run_app_parser.set_defaults(func=run_app_command_factory)

    def __init__(self, port, host, workers):
        self.port = port
        self.host = host
        self.workers = workers

    def run(self):
        command = f"uvicorn aiaio.app.app:app --host {self.host} --port {self.port}"
        command += f" --workers {self.workers}"

        logger.info(f"Starting server with command: {command}")

        if sys.platform == "win32":
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True, text=True, bufsize=1
            )
        else:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=True,
                text=True,
                bufsize=1,
                preexec_fn=os.setsid,
            )

        try:
            # Stream output in real-time
            while True:
                output = process.stdout.readline()
                if output:
                    print(output.strip())
                if process.poll() is not None:
                    break

            if process.returncode != 0:
                logger.error(f"Process exited with code {process.returncode}")
                sys.exit(process.returncode)

        except KeyboardInterrupt:
            logger.warning("Attempting to terminate the process...")
            if sys.platform == "win32":
                process.terminate()
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            logger.info("Process terminated by user")
            sys.exit(1)
