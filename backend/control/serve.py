"""Start the local Control web API with explicit private operator configuration.

One Uvicorn process, loopback only. The Next.js proxy holds the API token on
the server; worker credentials and model keys never enter browser settings.
"""

import argparse
import os
from pathlib import Path

import uvicorn

from backend.control.agent import _bound_review, build_case
from backend.control.agent_main import case_for_evidence, load_openai_settings, read_case_config
from backend.control.alerts import load_policy
from backend.control.openai_client import AgentAPIError, ResponsesClient
from backend.control.reporting import read_evidence
from backend.shared.settings import ControlSettings, ROOT, WorkerEndpoint


_CONTROL_KEYS = {"MESHMIND_CONTROL_API_TOKEN", "MESHMIND_CONTROL_API_URL"}
_VIEWER_KEYS = {"MESHMIND_VIEWER_HYDRO_TOKEN", "MESHMIND_VIEWER_FLOOD_TOKEN"}
_WORKER_KEYS = {"HYDRO_WORKER_URL", "HYDRO_WORKER_TOKEN", "FLOOD_WORKER_URL", "FLOOD_WORKER_TOKEN",
                "MESHMIND_CONTROL_SOURCE_IP", "MESHMIND_REQUEST_TIMEOUT_SECONDS",
                "MESHMIND_TASK_TIMEOUT_SECONDS", "MESHMIND_POLL_INTERVAL_SECONDS"}


def read_private_assignments(path, allowed):
    """Literal, bounded assignments only; no shell expansion or environment edits."""
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            raise ValueError
        result = {}
        for line in raw.decode("utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = line.removeprefix("export ")
            key, separator, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if separator != "=" or key not in allowed or key in result:
                raise ValueError
            if value[:1] in {"'", '"'}:
                if len(value) < 2 or value[-1] != value[0]:
                    raise ValueError
                value = value[1:-1]
            result[key] = value
        return result
    except (OSError, ValueError, UnicodeError):
        raise ValueError("Private configuration must contain only the documented literal assignments.") from None


def worker_settings(path=None):
    if path is None:
        return ControlSettings.from_env()
    values = read_private_assignments(path, _WORKER_KEYS)
    try:
        return ControlSettings(
            hydro=WorkerEndpoint(values.get("HYDRO_WORKER_URL", ""), "hydro-worker", values.get("HYDRO_WORKER_TOKEN") or None),
            flood=WorkerEndpoint(values.get("FLOOD_WORKER_URL", ""), "flood-worker", values.get("FLOOD_WORKER_TOKEN") or None),
            local_address=values.get("MESHMIND_CONTROL_SOURCE_IP") or None,
            request_timeout=float(values.get("MESHMIND_REQUEST_TIMEOUT_SECONDS", "15")),
            task_timeout=float(values.get("MESHMIND_TASK_TIMEOUT_SECONDS", "600")),
            poll_interval=float(values.get("MESHMIND_POLL_INTERVAL_SECONDS", "0.5")),
        )
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Worker settings do not satisfy their bounded configuration contract.") from None


def viewer_tokens(path=None):
    """Load optional role-scoped read-only credentials without changing the environment."""
    if path is None:
        return None
    values = read_private_assignments(path, _VIEWER_KEYS)
    if set(values) != _VIEWER_KEYS:
        raise ValueError("The viewer file requires a separate token for each worker role.")
    return {role: values[f"MESHMIND_VIEWER_{role.upper()}_TOKEN"] for role in ("hydro", "flood")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--input", type=Path, help="Review retained original evidence; no new worker dispatches.")
    mode.add_argument("--execute", action="store_true", help="Enable new worker investigations for the configured case.")
    parser.add_argument("--config", type=Path, default=ROOT / "config/test_case.example.json")
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--control-env-file", type=Path, help="Private MESHMIND_CONTROL_API_TOKEN (also used by the Next.js proxy).")
    parser.add_argument("--viewer-env-file", type=Path, help="Optional private read-only Hydro and Flood viewer tokens; never enables remote operator access.")
    parser.add_argument("--openai-env-file", type=Path, help="Private OPENAI_API_KEY and OPENAI_MODEL file.")
    parser.add_argument("--worker-env-file", type=Path, help="Private worker URLs, tokens and bounded Control settings; execute mode only.")
    parser.add_argument("--gpm-resources", nargs="+")
    parser.add_argument("--smap-resource")
    parser.add_argument("--history-dir", type=Path, default=ROOT / "outputs/debug/control-web")
    parser.add_argument("--host", choices=("127.0.0.1", "::1"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--check-config", action="store_true", help="Validate configuration without starting a server or making network calls.")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535.")
    if args.execute and (not args.gpm_resources or not args.smap_resource):
        parser.error("--execute requires configured --gpm-resources and --smap-resource.")
    if args.input and (args.gpm_resources or args.smap_resource or args.worker_env_file):
        parser.error("Retained review uses its original resources and does not load worker credentials.")
    try:
        from backend.control.web import ControlService, create_app

        values = read_private_assignments(args.control_env_file, _CONTROL_KEYS) if args.control_env_file else os.environ
        token = values.get("MESHMIND_CONTROL_API_TOKEN", "")
        config, policy = read_case_config(args.config), load_policy(args.rules)
        evidence, control = None, None
        if args.input:
            evidence, _digest = read_evidence(args.input)
            case = case_for_evidence(config, evidence)
            _bound_review(evidence, case, policy)
        else:
            case = build_case(config, args.gpm_resources, args.smap_resource)
            control = worker_settings(args.worker_env_file)
        client = ResponsesClient(load_openai_settings(args.openai_env_file))
        service = ControlService(case, policy, client, mode="execute" if args.execute else "review",
                                 evidence=evidence, control_settings=control, history_dir=args.history_dir)
        app = create_app(service=service, token=token, viewer_tokens=viewer_tokens(args.viewer_env_file))
    except (AgentAPIError, ValueError, TypeError, KeyError, OSError):
        print("Control configuration failed. Check the explicit case, evidence, policy and private settings; no request was sent.")
        return 2
    if args.check_config:
        print("Control web configuration: PASS. No API or worker requests sent.")
        return 0
    print("Control web API: local access only; one process. Session requests are retained in private history.", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, workers=1, reload=False, access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
