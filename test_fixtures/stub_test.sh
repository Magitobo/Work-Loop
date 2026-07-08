#!/bin/bash
# Stub test script for Work-Loop unit tests.
# Usage: stub_test.sh [--slow] [--fail]
#   --slow    Sleep 6 minutes to trigger timeout detection (past default 4-min threshold)
#   --fail    Exit with code 1 to simulate test failure

SLOW=0
FAIL=0
for arg in "$@"; do
  case "$arg" in
    --slow) SLOW=1 ;;
    --fail) FAIL=1 ;;
  esac
done

echo "stub_test: started" >> run.log

if [ $SLOW -eq 1 ]; then
  for i in $(seq 1 72); do
    sleep 5
    echo "stub_test: tick $i" >> run.log
  done
fi

echo "stub_test: done" >> run.log

if [ $FAIL -eq 1 ]; then
  exit 1
fi
exit 0
