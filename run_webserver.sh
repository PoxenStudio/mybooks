#!/bin/bash
python3 server.py --with-library=/data/books/library --port=8083 --host=127.0.0.1 --logging=info --log-file-prefix=/data/log/mybooks.log
