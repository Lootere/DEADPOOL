#!/bin/bash

set -e

cd /Lootere-Filter-Bot

echo "Installing requirements..."
pip3 install -U -r requirements.txt

echo "Starting Lootere Filter Bot..."
python3 bot.py
