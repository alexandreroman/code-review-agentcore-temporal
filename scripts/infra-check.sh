#!/usr/bin/env bash
# Checks the OpenTofu formatting and validates every stack (make infra-check).
#
# Validation needs no AWS access: each stack is initialised without its S3
# backend, in a separate data directory that leaves the real one untouched.
set -euo pipefail

tofu fmt -check -recursive infra

export TF_DATA_DIR=.terraform-validate
for stack in bootstrap aws github; do
  tofu -chdir="infra/$stack" init -backend=false -input=false >/dev/null
  tofu -chdir="infra/$stack" validate -no-color
done
