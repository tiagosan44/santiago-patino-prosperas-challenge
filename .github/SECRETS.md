# GitHub Actions secrets required

Configure these in **Repo Settings → Secrets and variables → Actions** before pushing to `main`.

| Secret | Value |
|--------|-------|
| `AWS_ACCESS_KEY_ID` | Access key of the `prosperas-ci` IAM user |
| `AWS_SECRET_ACCESS_KEY` | Secret key of the `prosperas-ci` IAM user |
| `AWS_REGION` | `us-east-1` |
| `AWS_ACCOUNT_ID` | `000758060526` (informational; not strictly used by the workflows) |
| `JWT_SECRET` | A random 64-byte hex string. Generate with: `python -c "import secrets; print(secrets.token_hex(32))"` |

## Creating the prosperas-ci IAM user

A minimal-but-sufficient policy is the AdministratorAccess managed policy
(simplest; rotate the key after the challenge ends). For a least-privilege
setup, attach a custom policy with terraform:* + iam:* (limited to the
project's resources) + ecr:Put/Get + ecs:UpdateService + s3 + cloudfront +
sqs + sns + dynamodb + cloudwatch + logs.

```
aws iam create-user --user-name prosperas-ci
aws iam attach-user-policy --user-name prosperas-ci \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
aws iam create-access-key --user-name prosperas-ci
```

The `create-access-key` output contains the AccessKeyId and SecretAccessKey
to set as the GitHub secrets. **DELETE THIS USER** after the take-home is
reviewed and the URL is no longer needed.
