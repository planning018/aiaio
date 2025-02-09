import argparse

from aiaio import __version__
from aiaio.cli.run_app import RunAppCommand


def main():
    parser = argparse.ArgumentParser(
        "aiaio cli",
        usage="aiaio <command> [<args>]",
        epilog="For more information about a command, run: `aiaio <command> --help`",
    )
    parser.add_argument("--version", "-v", help="Display version", action="store_true")
    commands_parser = parser.add_subparsers(help="commands")

    # Register commands
    RunAppCommand.register_subcommand(commands_parser)

    args = parser.parse_args()

    if args.version:
        print(__version__)
        exit(0)

    if not hasattr(args, "func"):
        parser.print_help()
        exit(1)

    command = args.func(args)
    command.run()


if __name__ == "__main__":
    main()
