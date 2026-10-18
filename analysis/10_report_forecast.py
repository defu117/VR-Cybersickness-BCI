import argparse
from pathlib import Path
from forecasting.report import make_report

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_directory")
    args = parser.parse_args()
    print(make_report(Path(args.run_directory)).to_string(index=False))
