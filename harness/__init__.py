"""InsightFlow local development harness.

Run every development task through it, so tasks start only when the machine has enough
free memory, CPU and disk, and are stopped before they can hang the system.

    python -m harness check            # resource report
    python -m harness test [args]      # guarded pytest
    python -m harness run -- <cmd>     # guarded command
    python -m harness status           # development dashboard
    python -m harness history          # recent runs
"""
