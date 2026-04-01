"""atlas-parser stream consumer — listens for ScanResultEvent on Redis.

Consumes ``atlas.scan.results``, parses each pipeline config into nodes
and edges, and publishes a ParseResultEvent to ``atlas.parse.results``.
"""

import json
import logging
import os
import sys

from atlas_parser.orchestrator import ParserOrchestrator
from atlas_sdk.enums import Platform
from atlas_sdk.events import ParseResultEvent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("atlas_parser")


def main() -> None:
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")

    try:
        import redis as _redis
    except ImportError:
        logger.error("redis package is required: pip install redis")
        sys.exit(1)

    logger.info("Connecting to Redis at %s ...", redis_url)
    client = _redis.from_url(redis_url, decode_responses=True)

    stream_in = "atlas.scan.results"
    stream_out = "atlas.parse.results"
    group = "atlas-parser"
    consumer = "parser-1"

    try:
        client.xgroup_create(stream_in, group, id="0", mkstream=True)
    except _redis.exceptions.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise

    logger.info("Listening on '%s' (group=%s)...", stream_in, group)
    orchestrator = ParserOrchestrator()

    while True:
        try:
            messages = client.xreadgroup(
                group, consumer, {stream_in: ">"}, count=1, block=5000
            )
            if not messages:
                continue

            for _stream_name, entries in messages:
                for msg_id, fields in entries:
                    try:
                        payload = json.loads(fields.get("data") or fields.get("payload", "{}"))
                        scan_request_id = payload.get("event_id", "")
                        platform_str = payload.get("platform", "jenkins")
                        platform = Platform(platform_str)
                        configs = payload.get("pipeline_configs", [])

                        logger.info(
                            "Parsing %d config(s) for scan %s (platform=%s)",
                            len(configs), scan_request_id, platform,
                        )

                        all_nodes: list[dict] = []
                        all_edges: list[dict] = []

                        for cfg in configs:
                            content = cfg.get("content", "")
                            if not content:
                                continue
                            result = orchestrator.parse(content, platform)
                            all_nodes.extend(
                                n.model_dump(mode="json") for n in result.nodes
                            )
                            all_edges.extend(
                                e.model_dump(mode="json") for e in result.edges
                            )

                        event = ParseResultEvent(
                            scan_request_id=scan_request_id,
                            nodes=all_nodes,
                            edges=all_edges,
                        )
                        client.xadd(stream_out, {"payload": event.model_dump_json()})
                        logger.info(
                            "Published %d nodes, %d edges to '%s'",
                            len(all_nodes), len(all_edges), stream_out,
                        )

                    except Exception as exc:  # noqa: BLE001
                        logger.error("Failed to process %s: %s", msg_id, exc)
                    finally:
                        client.xack(stream_in, group, msg_id)

        except KeyboardInterrupt:
            logger.info("Shutting down parser consumer.")
            break


if __name__ == "__main__":
    main()
