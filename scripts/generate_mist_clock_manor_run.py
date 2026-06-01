from __future__ import annotations

from generate_case_run import main as generate_case_run_main


def main() -> None:
    generate_case_run_main(["--case-id", "mist_clock_manor"])


if __name__ == "__main__":
    main()
