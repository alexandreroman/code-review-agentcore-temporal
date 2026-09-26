resource "aws_s3_bucket" "snapshots" {
  bucket_prefix = "${local.component_prefix}-snapshots-"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "snapshots" {
  bucket                  = aws_s3_bucket.snapshots.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "snapshots" {
  bucket = aws_s3_bucket.snapshots.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Safety net for workflows that never clean up their snapshots.
resource "aws_s3_bucket_lifecycle_configuration" "snapshots" {
  bucket = aws_s3_bucket.snapshots.id
  rule {
    id     = "expire-snapshots"
    status = "Enabled"
    filter {}
    expiration {
      days = 7
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}
