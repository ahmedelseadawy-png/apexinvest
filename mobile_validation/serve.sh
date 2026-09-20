#!/bin/bash
# usage: serve.sh <offline|real> <port> ; stops via pidfile serve.<port>.pid
MODE=$1; PORT=$2
D="$(cd "$(dirname "$0")" && pwd)"
BACK=${BACKEND:-$D/../apexinvest_backend}
if [ -f $D/serve.$PORT.pid ]; then kill $(cat $D/serve.$PORT.pid) 2>/dev/null; rm -f $D/serve.$PORT.pid; sleep 1; fi
[ "$MODE" = "stop" ] && exit 0
cd $D
if [ "$MODE" = "offline" ]; then
  nohup python $D/offline_server.py $BACK $PORT > /tmp/apex_srv.$PORT.log 2>&1 &
else
  cd $BACK && nohup python -m uvicorn apexinvest.api.main:app --host 127.0.0.1 --port $PORT > /tmp/apex_srv.$PORT.log 2>&1 &
fi
echo $! > $D/serve.$PORT.pid
sleep 5
curl -s localhost:$PORT/v1/health; echo
