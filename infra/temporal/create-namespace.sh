#!/bin/sh
set -eu
: "${TEMPORAL_ADDRESS:?missing Temporal address}"
: "${TEMPORAL_NAMESPACE:?missing namespace}"
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if temporal operator cluster health --address "$TEMPORAL_ADDRESS"; then
    if temporal operator namespace describe --address "$TEMPORAL_ADDRESS" -n "$TEMPORAL_NAMESPACE"; then
      exit 0
    fi
    temporal operator namespace create --address "$TEMPORAL_ADDRESS" -n "$TEMPORAL_NAMESPACE"
    exit 0
  fi
  sleep 2
done
echo "Temporal did not become healthy; namespace was not created" >&2
exit 1
