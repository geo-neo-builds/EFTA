"""Entrypoint for the document scraper Cloud Run Job."""

import json
import logging
import sys

from google.cloud import pubsub_v1

from pipeline.config import config
from pipeline.scraper.doj_scraper import DOJScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("Starting document scraper...")

    # Run DOJ scraper
    scraper = DOJScraper()
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
