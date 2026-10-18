#!/usr/bin/env sh

# Host
if [ -z "$BW_HOST" ]
then
    export BW_HOST="0.0.0.0"
fi

# Port
if [ -z "$BW_PORT" ]
then
    export BW_PORT=3333
fi

# The app writes its database, keys and media under /app/data. A volume created by an older image,
# which ran as root, is root-owned: say how to fix it instead of failing later on the first write.
if [ -d /app/data ] && [ ! -w /app/data ]
then
    echo "Brick Work cannot write to /app/data (it runs as uid $(id -u))." >&2
    echo "On the host: sudo chown -R $(id -u):$(id -g) ./data   (the folder mounted at /app/data)" >&2
    exit 1
fi

# Execute the WSGI server
exec gunicorn --bind "${BW_HOST}:${BW_PORT}" "wsgi:application" --worker-class "gevent" --workers 1 --timeout 120 "$@"
