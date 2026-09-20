#!/bin/bash
# usage: run_cloud_sim.sh <start|stop> <port> [workers]   -> production-mode server, real start-command flags
CMD=$1; PORT=$2; W=${3:-1}
D="$(cd "$(dirname "$0")" && pwd)"
VENV=${VENV:-/tmp/claude-0/venv_lock}
if [ -f $D/cloud.$PORT.pid ]; then kill $(cat $D/cloud.$PORT.pid) 2>/dev/null; rm -f $D/cloud.$PORT.pid; sleep 1; fi
[ "$CMD" = "stop" ] && exit 0
cd $D
export PORT APEX_ENV=production PYTHONPATH=$D
if [ "$NOKEYS" = "1" ]; then unset APEX_ACCESS_KEYS; else export APEX_ACCESS_KEYS="${APEX_ACCESS_KEYS:-ahmed:Cloud-Test-Key-0123456789}"; fi
export APEX_RL_HEAVY=${APEX_RL_HEAVY:-100000} APEX_RL_ANALYSIS=${APEX_RL_ANALYSIS:-100000} APEX_RL_GENERAL=${APEX_RL_GENERAL:-100000} APEX_HEAVY_CONCURRENCY=${APEX_HEAVY_CONCURRENCY:-8}
nohup $VENV/bin/python -m uvicorn cloud_sim_app:app --host 0.0.0.0 --port $PORT --workers $W --proxy-headers --forwarded-allow-ips '*' --no-access-log --no-server-header --timeout-graceful-shutdown 20 > /tmp/apex_cloud.$PORT.log 2>&1 &
echo $! > $D/cloud.$PORT.pid
for i in $(seq 1 30); do sleep 1; curl -sf localhost:$PORT/v1/health && break; done; echo
