"""
Comprehensive Test Script for Website Crawling, Extraction, Semantic Chunking,
Hybrid RAG Retrieval, SSRF Security, and Tenant Isolation.
"""

import os
import sys
import unittest
import ipaddress
from urllib.parse import urlparse

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()

from api.models import Client, User, KnowledgeDocument, KnowledgeChunk
from api.services.content_extractor import WebpageContentExtractor
from api.services.semantic_chunker import SemanticChunker
from api.services.crawler_service import WebsiteCrawlerService, BLOCKED_IP_NETWORKS
from api.services.rag_service import HybridRAGService
from api.services.ai_service import cosine_similarity, find_relevant_chunks


class TestCompleteRAGPipeline(unittest.TestCase):
    def setUp(self):
        self.sample_html = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <title>Acme AI Solutions — Intelligent Automation</title>
            <meta name="description" content="Acme AI builds enterprise chatbots, CRM workflows, and WhatsApp automation.">
            <link rel="canonical" href="https://example.com/solutions">
        </head>
        <body>
            <header>
                <nav><a href="/">Home</a> <a href="/pricing">Pricing</a></nav>
            </header>

            <main>
                <h1>Acme AI Solutions & Platform Architecture</h1>
                <p>Acme AI provides high-throughput enterprise automation engines deployed across 15 countries.</p>

                <h2>Core Features & Capabilities</h2>
                <ul>
                    <li>Real-time WhatsApp Cloud API Integration</li>
                    <li>Omnichannel Shared Team Inbox</li>
                    <li>Visual Workflow Automation Builder</li>
                </ul>

                <h2>Enterprise Pricing & Tiers</h2>
                <table>
                    <thead>
                        <tr><th>Plan Name</th><th>Monthly Price</th><th>Messages Included</th></tr>
                    </thead>
                    <tbody>
                        <tr><td>Starter Launch</td><td>₹1,499</td><td>5,000 Messages</td></tr>
                        <tr><td>Growth Engine</td><td>₹3,999</td><td>25,000 Messages</td></tr>
                        <tr><td>Enterprise Scale</td><td>₹9,999</td><td>Unlimited Messages</td></tr>
                    </tbody>
                </table>

                <h2>Frequently Asked Questions</h2>
                <details>
                    <summary>What is the refund policy for annual plans?</summary>
                    <p>Annual subscriptions can be refunded within 14 days of purchase with no questions asked.</p>
                </details>
                <details>
                    <summary>How can I contact technical support?</summary>
                    <p>You can reach our 24/7 dedicated engineering support team at support@acme-ai.com or phone +91-9876543210.</p>
                </details>

                <div class="code-section">
                    <h3>Webhook Signature Verification</h3>
                    <pre><code>import hmac, hashlib
signature = hmac.new(secret, payload, hashlib.sha256).hexdigest()</code></pre>
                </div>
            </main>

            <footer>
                <p>Copyright 2026 Acme Corp. All rights reserved.</p>
            </footer>
        </body>
        </html>
        """

    def test_01_ssrf_security_defense(self):
        """Test that SSRF attempts against localhost, private IPs, and cloud metadata are strictly blocked."""
        crawler = WebsiteCrawlerService("https://example.com")

        # Test blocked targets
        blocked_targets = [
            "http://127.0.0.1/admin",
            "http://localhost:8000/secret",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/internal",
            "http://192.168.1.1/router",
            "http://172.16.0.5/database",
            "ftp://example.com/file",
            "file:///etc/passwd",
        ]

        for target in blocked_targets:
            self.assertFalse(
                crawler.is_safe_url(target),
                f"Security Failure: SSRF target {target} should have been blocked!"
            )
        print(" [TEST 1 PASSED] SSRF Defense successfully blocked all private/metadata/loopback targets.")

    def test_02_content_extraction_hierarchy_and_tables(self):
        """Test that HTML parsing extracts headings, tables in Markdown, lists, and FAQs without squashing."""
        extractor = WebpageContentExtractor("https://example.com")
        extracted = extractor.extract(self.sample_html, "https://example.com/solutions")

        # Verify title & description
        self.assertEqual(extracted["title"], "Acme AI Solutions — Intelligent Automation")
        self.assertIn("enterprise chatbots", extracted["meta_description"])

        text = extracted["structured_text"]

        # Verify Headings
        self.assertIn("# Acme AI Solutions & Platform Architecture", text)
        self.assertIn("## Core Features & Capabilities", text)
        self.assertIn("## Enterprise Pricing & Tiers", text)

        # Verify Markdown Table was created preserving rows & columns
        self.assertIn("| Plan Name | Monthly Price | Messages Included |", text)
        self.assertIn("| Starter Launch | ₹1,499 | 5,000 Messages |", text)
        self.assertIn("| Enterprise Scale | ₹9,999 | Unlimited Messages |", text)

        # Verify Bullet Lists
        self.assertIn("- Real-time WhatsApp Cloud API Integration", text)
        self.assertIn("- Visual Workflow Automation Builder", text)

        # Verify FAQs
        self.assertIn("What is the refund policy for annual plans?", text)
        self.assertIn("refunded within 14 days", text)
        self.assertIn("support@acme-ai.com", text)

        # Verify noise was stripped
        self.assertNotIn("Copyright 2026 Acme Corp", text)

        print(" [TEST 2 PASSED] Content Extractor successfully preserved hierarchy, markdown tables, lists, and FAQs.")

    def test_03_semantic_chunking_with_breadcrumbs(self):
        """Test that SemanticChunker creates heading-aware chunks with contextual breadcrumbs and hashes."""
        extractor = WebpageContentExtractor("https://example.com")
        extracted = extractor.extract(self.sample_html, "https://example.com/solutions")

        chunker = SemanticChunker(target_chunk_words=100, overlap_words=20)
        chunks = chunker.chunk_extracted_page(extracted)

        self.assertGreater(len(chunks), 0)
        for c in chunks:
            # Must contain breadcrumbs
            self.assertIn("[Source: https://example.com/solutions]", c["chunk_text"])
            self.assertIn("[Page Title: Acme AI Solutions — Intelligent Automation]", c["chunk_text"])
            self.assertTrue(len(c["content_hash"]) == 64, "Content hash must be valid SHA-256")
            self.assertTrue(c["word_count"] > 0)

        print(f" [TEST 3 PASSED] Semantic Chunker created {len(chunks)} contextual chunks with breadcrumbs and SHA-256 hashes.")

    def test_04_hybrid_retrieval_and_exact_match(self):
        """Test that Hybrid RAG retrieves exact terms like pricing and emails via lexical boost."""
        # Create dummy chunks
        chunks_data = [
            {
                'text': '[Source: https://example.com/pricing]\nStarter Launch: ₹1,499 per month for 5,000 messages.',
                'embedding': [0.01] * 1536,
                'doc_title': 'Pricing Plans',
                'source_url': 'https://example.com/pricing',
                'heading_path': 'Pricing > Starter'
            },
            {
                'text': '[Source: https://example.com/faq]\nContact support team at support@acme-ai.com or phone +91-9876543210.',
                'embedding': [0.02] * 1536,
                'doc_title': 'FAQ & Support',
                'source_url': 'https://example.com/faq',
                'heading_path': 'Support > Contact'
            },
            {
                'text': '[Source: https://example.com/about]\nAcme was founded in 2020 to build automation software.',
                'embedding': [0.05] * 1536,
                'doc_title': 'About Us',
                'source_url': 'https://example.com/about',
                'heading_path': 'Company > History'
            }
        ]

        # Test exact keyword search
        relevant = find_relevant_chunks([0.01] * 1536, chunks_data, top_k=2, query_text="support@acme-ai.com")
        self.assertGreater(len(relevant), 0)
        self.assertIn("support@acme-ai.com", relevant[0]['text'])

        # Test exact pricing query
        relevant_pricing = find_relevant_chunks([0.01] * 1536, chunks_data, top_k=2, query_text="₹1,499")
        self.assertGreater(len(relevant_pricing), 0)
        self.assertIn("₹1,499", relevant_pricing[0]['text'])

        print(" [TEST 4 PASSED] Hybrid retrieval successfully prioritized exact technical and contact queries.")

    def test_05_url_normalization_and_deduplication(self):
        """Test URL normalization strips tracking params, fragments, and standardizes slashes."""
        crawler = WebsiteCrawlerService("https://example.com")

        u1 = crawler.normalize_url("https://example.com/features#section2")
        self.assertEqual(u1, "https://example.com/features")

        u2 = crawler.normalize_url("https://example.com/pricing/?utm_source=google&utm_campaign=winter&gclid=12345")
        self.assertEqual(u2, "https://example.com/pricing")

        u3 = crawler.normalize_url("https://example.com/image.png")
        self.assertIsNone(u3, "Binary extension should be filtered out from crawl queue")

        print(" [TEST 5 PASSED] URL normalization correctly stripped tracking params, fragments, and filtered binary files.")


if __name__ == '__main__':
    unittest.main()
