"""Entrypoint for the document scraper Cloud Run Job.

Usage:
    python -m pipeline.jobs.run_scraper                       # full crawl
    python -m pipeline.jobs.run_scraper data-set-1-files      # crawl one path
    python -m pipeline.jobs.run_scraper <full-url>            # crawl from a URL
    python -m pipeline.jobs.run_scraper sequential 1          # data set 1 by ID
    python -m pipeline.jobs.run_scraper sequential 1 1 100    # data set 1, ids 1-100
"""

import json
import logging
import sys

from google.cloud import pubsub_v1

from pipeline.config import config
from pipeline.scraper.doj_scraper import DOJ_BASE_URL, DOJ_DISCLOSURES_URL, DOJScraper
from pipeline.scraper.sequential_scraper import SequentialDOJScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("Starting document scraper...")

    args = sys.argv[1:]

    # Sequential mode: bypass paginated listing pages
    if args and args[0] == "sequential":
        if len(args) < 2:
            print("Usage: run_scraper sequential <data_set> [start] [end]")
            sys.exit(1)
        data_set = int(args[1])
        start = int(args[2]) if len(args) > 2 else 1
        end = int(args[3]) if len(args) > 3 else None
        scraper = SequentialDOJScraper(data_set=data_set, start=start, end=end)
        documents = scraper.run()
    else:
        # Crawl mode (uses paginated listing pages, may hit rate limits)
        if args:
            target = args[0]
            start_url = target if target.startswith("http") else (
                f"{DOJ_BASE_URL}/epstein/doj-disclosures/{target}"
            )
        else:
            start_url = DOJ_DISCLOSURES_URL
        scraper = DOJScraper(start_url=start_url)
        documents = scraper.run()

    if not documents:
        logger.info("No new documents to process.")
        return

    # Publish messages to Pub/Sub for each new/updated document
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(config.gcp_project_id, config.pubsub_topic_downloaded)

    for doc in documents:
        message = json.dumps({"document_id": doc.id}).encode("utf-8")
        future = publisher.publish(topic_path, message)
        logger.info("Published message for document %s: %s", doc.id, future.result())

    logger.info("Scraper complete. Published %d documents.", len(documents))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Scraper failed")
        sys.exit(1)
