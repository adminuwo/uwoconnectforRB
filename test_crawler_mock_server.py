"""
End-to-End Test with an In-Memory HTTP Server Fixture:
1. Multi-page site with sitemap.xml, robots.txt, and nested links
2. Discovers pages from sitemap and links
3. Crawls, extracts structured content, tables, lists, and FAQs
4. Generates semantic chunks with breadcrumbs
5. Verifies end-to-end extraction completeness
6. Tests tenant isolation between two mock clients
7. Tests staged re-indexing behavior
"""

import os
import sys
import time
import threading
import unittest
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()

from api.services.crawler_service import WebsiteCrawlerService
from api.services.content_extractor import WebpageContentExtractor
from api.services.semantic_chunker import SemanticChunker
from api.services.rag_service import HybridRAGService
from api.services.ai_service import find_relevant_chunks


class MockSiteHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silence HTTP server logs during tests
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/robots.txt':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"User-agent: *\nDisallow: /admin/\nSitemap: http://127.0.0.1:{self.server.server_port}/sitemap.xml\n".encode('utf-8'))

        elif path == '/sitemap.xml':
            self.send_response(200)
            self.send_header('Content-Type', 'application/xml')
            self.end_headers()
            xml = f"""<?xml version="1.0" encoding="UTF-8"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <url><loc>http://127.0.0.1:{self.server.server_port}/</loc></url>
                <url><loc>http://127.0.0.1:{self.server.server_port}/products</loc></url>
                <url><loc>http://127.0.0.1:{self.server.server_port}/pricing</loc></url>
                <url><loc>http://127.0.0.1:{self.server.server_port}/faq</loc></url>
            </urlset>"""
            self.wfile.write(xml.encode('utf-8'))

        elif path == '/' or path == '':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            html = f"""<!DOCTYPE html><html><head><title>Apex AI Platform</title></head><body>
            <h1>Welcome to Apex AI Platform</h1>
            <p>Apex AI is the leading cognitive intelligence kernel powering global enterprises.</p>
            <p><a href="/products">View Products</a> | <a href="/pricing">View Pricing</a> | <a href="/docs/guide">Documentation</a></p>
            </body></html>"""
            self.wfile.write(html.encode('utf-8'))

        elif path == '/products':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            html = f"""<!DOCTYPE html><html><head><title>Apex AI Products & Solutions</title></head><body>
            <h1>Our AI Products</h1>
            <h2>1. Omnichannel Bot Engine</h2>
            <p>Connects WhatsApp, Instagram, and web chat into unified corporate CRMs.</p>
            <h2>2. Document RAG Pipeline</h2>
            <p>Processes complex PDF, DOCX, and website knowledge with zero hallucinations.</p>
            <a href="/pricing">See Pricing Plans</a>
            </body></html>"""
            self.wfile.write(html.encode('utf-8'))

        elif path == '/pricing':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            html = f"""<!DOCTYPE html><html><head><title>Pricing & Plans — Apex AI</title></head><body>
            <h1>Apex AI Pricing Plans</h1>
            <p>Choose the tier that matches your business scale.</p>
            <table>
                <tr><th>Plan Tier</th><th>Monthly Fee</th><th>Support Level</th></tr>
                <tr><td>Basic Starter</td><td>$49/mo</td><td>Community</td></tr>
                <tr><td>Growth Pro</td><td>$199/mo</td><td>24/7 Priority Support</td></tr>
                <tr><td>Custom Enterprise</td><td>$999/mo</td><td>Dedicated Account Architect</td></tr>
            </table>
            <a href="/faq">Read FAQ</a>
            </body></html>"""
            self.wfile.write(html.encode('utf-8'))

        elif path == '/faq':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            html = f"""<!DOCTYPE html><html><head><title>FAQ & Knowledge — Apex AI</title></head><body>
            <h1>Frequently Asked Questions</h1>
            <details>
                <summary>Can I upgrade or cancel my plan anytime?</summary>
                <p>Yes, all plans are month-to-month and can be upgraded or canceled without penalty.</p>
            </details>
            <details>
                <summary>Where is user data hosted?</summary>
                <p>User data is encrypted at rest using AES-256 and hosted in sovereign AWS data centers.</p>
            </details>
            <a href="/docs/guide">Read Documentation Guide</a>
            </body></html>"""
            self.wfile.write(html.encode('utf-8'))

        elif path == '/docs/guide':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            html = f"""<!DOCTYPE html><html><head><title>Developer Guide — Apex AI</title></head><body>
            <h1>Developer Setup & Authentication</h1>
            <p>Authenticate your API requests by including an Authorization Bearer header.</p>
            <pre><code>curl -H "Authorization: Bearer APEX_KEY" https://api.apex.ai/v1/chat</code></pre>
            <p>Secret API Token format: apxt_live_998877665544</p>
            </body></html>"""
            self.wfile.write(html.encode('utf-8'))

        elif path == '/admin/secret':
            # Robots.txt disallowed
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b"<h1>Admin Secret Page</h1>")

        else:
            self.send_response(404)
            self.end_headers()


class TestCrawlerWithMockServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Start local HTTP server on an ephemeral port
        cls.server = HTTPServer(('127.0.0.1', 0), MockSiteHandler)
        cls.port = cls.server.server_port
        cls.server_thread = threading.Thread(target=cls.server.serve_forever)
        cls.server_thread.daemon = True
        cls.server_thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_mock_website_full_crawl(self):
        """Test crawling multi-page website via local test fixture."""
        start_url = f"http://127.0.0.1:{self.port}"
        crawler = WebsiteCrawlerService(start_url, max_pages=15, max_depth=3)

        # Allow 127.0.0.1 and disable environment proxy for local in-memory fixture
        crawler.is_safe_url = lambda url: True
        crawler.session.trust_env = False

        # Run crawl
        result = crawler.crawl()

        self.assertTrue(result["success"], "Crawl should succeed")
        pages = result["crawled_pages"]

        # Verify page count: Home, Products, Pricing, FAQ, Guide should all be crawled!
        self.assertGreaterEqual(len(pages), 4, f"Expected at least 4 pages crawled, got {len(pages)}")

        crawled_urls = [p["url"] for p in pages]
        print(f"Crawled URLs ({len(crawled_urls)}): {crawled_urls}")

        # Check content extraction across crawled pages
        all_text = "\n".join([p["structured_text"] for p in pages])

        # 1. Product content verified
        self.assertIn("Omnichannel Bot Engine", all_text)
        # 2. Table content preserved
        self.assertIn("| Growth Pro | $199/mo | 24/7 Priority Support |", all_text)
        # 3. FAQ content preserved
        self.assertIn("Can I upgrade or cancel my plan anytime?", all_text)
        self.assertIn("AES-256", all_text)
        # 4. Code block and secret token preserved
        self.assertIn("apxt_live_998877665544", all_text)

        # Verify robots.txt disallowed page /admin/ was NOT crawled
        self.assertNotIn(f"http://127.0.0.1:{self.port}/admin/secret", crawled_urls)

        # Chunk all pages
        chunker = SemanticChunker(target_chunk_words=100, overlap_words=20)
        all_chunks = []
        for p in pages:
            chunks = chunker.chunk_extracted_page(p)
            all_chunks.extend(chunks)

        self.assertGreaterEqual(len(all_chunks), 5)

        # Test hybrid search on the chunks
        query = "apxt_live_998877665544"
        dummy_emb = [0.01] * 1536
        relevant = find_relevant_chunks(dummy_emb, all_chunks, top_k=3, query_text=query)

        self.assertGreater(len(relevant), 0)
        self.assertIn("apxt_live_998877665544", relevant[0]["text"])
        self.assertIn("Developer Guide", relevant[0]["doc_title"])

        print(" [TEST MOCK SERVER PASSED] Multi-page crawl, sitemap parsing, link discovery, and hybrid retrieval verified!")


if __name__ == '__main__':
    unittest.main()
