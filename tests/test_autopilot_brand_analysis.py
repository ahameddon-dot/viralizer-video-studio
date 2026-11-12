import socket
import unittest
from unittest.mock import patch

import httpx

from autopilot_brand_analysis import analyze_brand_sources


class BrandAnalysisTests(unittest.IsolatedAsyncioTestCase):
    async def test_extracts_evidence_based_brand_draft(self):
        html=b'''<html><head><title>Northstar Analytics</title><meta name="description" content="Commerce analytics for independent stores"></head><body><h1>Grow your ecommerce store</h1><h2>Conversion insights</h2><p>Learn practical analytics guides for ecommerce founders and improve conversion.</p></body></html>'''
        transport=httpx.MockTransport(lambda request:httpx.Response(200,headers={"content-type":"text/html"},content=html))
        with patch("autopilot_brand_analysis.socket.getaddrinfo",return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,"",("93.184.216.34",443))]):
            async with httpx.AsyncClient(transport=transport) as client:
                result=await analyze_brand_sources("https://example.com",[],client)
        self.assertEqual("draft_requires_confirmation",result["status"])
        self.assertEqual("analyzed",result["sources"][0]["status"])
        self.assertIn("ecommerce",result["draft"]["areas_of_interest"])
        self.assertEqual("Business & Finance",result["draft"]["category"])
        self.assertIn("customer must review",result["disclosure"].lower())

    async def test_extracts_youtube_creator_identity_category_and_audience(self):
        html=b'''<html><head><meta property="og:title" content="Irfan's view"><meta property="og:description" content="I love Food and Living. I vlog and do Food Reviews."></head><body><script>{"channelId":"UChL9x-Q75LCuYHIFRDT_T1A","ownerChannelName":"Irfan's view","description":"I love Food and Living. I vlog and do Food Reviews.","title":{"runs":[{"text":"Street food review in Chennai"}]}}</script></body></html>'''
        transport=httpx.MockTransport(lambda request:httpx.Response(200,headers={"content-type":"text/html"},content=html))
        with patch("autopilot_brand_analysis.socket.getaddrinfo",return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,"",("142.250.1.1",443))]):
            async with httpx.AsyncClient(transport=transport) as client:
                result=await analyze_brand_sources("https://youtube.com/@irfansview1",[],client)
        self.assertEqual("Irfan's view",result["draft"]["brand_name"])
        self.assertEqual("creator",result["draft"]["identity_type"])
        self.assertEqual("Food & Cooking",result["draft"]["category"])
        self.assertIn("food lovers",result["draft"]["audiences"][0])

    async def test_blocks_private_network_targets(self):
        with patch("autopilot_brand_analysis.socket.getaddrinfo",return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,"",("127.0.0.1",80))]):
            result=await analyze_brand_sources("http://localhost",[])
        self.assertEqual("unavailable",result["sources"][0]["status"])
        self.assertIn("not allowed",result["sources"][0]["reason"])

    async def test_social_block_is_reported_not_fabricated(self):
        transport=httpx.MockTransport(lambda request:httpx.Response(403,headers={"content-type":"text/html"}))
        with patch("autopilot_brand_analysis.socket.getaddrinfo",return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,"",("142.250.1.1",443))]):
            async with httpx.AsyncClient(transport=transport) as client:
                result=await analyze_brand_sources("",["https://youtube.com/@brand"],client)
        self.assertEqual("connection_required",result["sources"][0]["status"])
        self.assertEqual([],result["draft"]["areas_of_interest"])


if __name__ == "__main__": unittest.main()
