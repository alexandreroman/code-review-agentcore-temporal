#!/usr/bin/env bash
# Applies the aws stack, keeping the endpoints of every build a pinned
# workflow might still use (make infra).
set -euo pipefail

source scripts/lib.sh

aws_apply
