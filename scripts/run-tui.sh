#!/bin/bash
# Legacy TUI demo script - redirects to new demo framework
#
# This script now runs the TiKV demo using the new demo framework.
# For rate limiter demo, use: ./scripts/run-demo.sh ratelimiter

exec ./scripts/run-demo.sh tikv
