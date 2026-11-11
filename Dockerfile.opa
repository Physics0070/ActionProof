# syntax=docker/dockerfile:1
# Policy sidecar for hosts without bind mounts (Render). Same OPA version as docker-compose.yml.
# No --watch: a policy change is a reviewed redeploy (ADR-005).
FROM openpolicyagent/opa:1.22.2
COPY policy /policy
COPY docker/opa/authz.rego /policy/authz.rego
EXPOSE 8181
CMD ["run", "--server", "--addr=0.0.0.0:8181", "--log-level=error", "--authorization=basic", "/policy"]
