#!/usr/bin/env python3
"""
API Verification Script
Tests all API endpoints across all LLM categories to verify they return valid responses.
"""

import json
import os
import asyncio
import aiohttp
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
import re

class APIVerifier:
    def __init__(self, categories_dir: str):
        self.categories_dir = Path(categories_dir)
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "total_apis": 0,
            "total_endpoints": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "categories": {}
        }

    def load_all_categories(self) -> Dict[str, Any]:
        """Load all category JSON files."""
        categories = {}
        for json_file in self.categories_dir.glob("*.json"):
            if json_file.name == "index.json":
                continue
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    categories[data['category']] = data
            except Exception as e:
                print(f"❌ Error loading {json_file.name}: {e}")
        return categories

    def extract_endpoints(self, category_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract all endpoints from a category."""
        endpoints = []
        for api in category_data.get('apis', []):
            for endpoint in api.get('endpoints', []):
                # Build test URL from direct_url and sample_request
                test_url = endpoint.get('direct_url', '')
                sample_url = endpoint.get('sample_request', '')
                
                # Prefer sample_request if available, otherwise use direct_url
                url_to_test = sample_url if sample_url else test_url
                
                # Replace path parameters if needed
                if '{' in url_to_test:
                    # Replace common path parameters with example values
                    url_to_test = url_to_test.replace('{coin_id}', 'bitcoin')
                    url_to_test = url_to_test.replace('{id}', '1')
                    url_to_test = url_to_test.replace('{isbn}', '9780261103573')
                
                endpoints.append({
                    'category': category_data['category'],
                    'api_id': api.get('id', 'unknown'),
                    'api_name': api.get('name', 'Unknown'),
                    'path': endpoint.get('path', ''),
                    'method': endpoint.get('method', 'GET'),
                    'url': url_to_test,
                    'auth_required': api.get('auth_required', False),
                    'sample_url': sample_url
                })
        return endpoints

    async def test_endpoint(self, session: aiohttp.ClientSession, endpoint: Dict[str, Any]) -> Dict[str, Any]:
        """Test a single API endpoint."""
        
        try:
            url = endpoint.get('url', '')
            
            if not url:
                return {
                    'endpoint': endpoint,
                    'status': 'skipped',
                    'reason': 'No URL provided'
                }
            
            if url.startswith('http://'):
                return {
                    'endpoint': endpoint,
                    'status': 'skipped',
                    'reason': 'HTTP URL (HTTPS only supported)'
                }
            
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=15),
                headers={'User-Agent': 'API-Verifier/1.0'}
            ) as response:
                status = response.status
                
                if status == 200:
                    # Try to parse JSON response
                    try:
                        content_type = response.headers.get('Content-Type', '')
                        if 'application/json' in content_type or 'text/' in content_type:
                            data = await response.text()
                            if data.strip().startswith('{') or data.strip().startswith('['):
                                json_data = json.loads(data)
                                return {
                                    'endpoint': endpoint,
                                    'status': 'passed',
                                    'status_code': status,
                                    'response_size': len(data),
                                    'response_preview': str(json_data)[:200]
                                }
                        else:
                            return {
                                'endpoint': endpoint,
                                'status': 'passed',
                                'status_code': status,
                                'content_type': content_type,
                                'note': 'Non-JSON response'
                            }
                    except:
                        return {
                            'endpoint': endpoint,
                            'status': 'passed',
                            'status_code': status,
                            'note': 'Response received but not JSON'
                        }
                elif status in [401, 403]:
                    return {
                        'endpoint': endpoint,
                        'status': 'skipped',
                        'status_code': status,
                        'reason': 'Authentication required'
                    }
                elif status == 429:
                    return {
                        'endpoint': endpoint,
                        'status': 'skipped',
                        'status_code': status,
                        'reason': 'Rate limited'
                    }
                elif status in [404, 500, 502, 503]:
                    return {
                        'endpoint': endpoint,
                        'status': 'failed',
                        'status_code': status,
                        'reason': f'HTTP {status}'
                    }
                else:
                    return {
                        'endpoint': endpoint,
                        'status': 'failed',
                        'status_code': status,
                        'reason': f'Unexpected status: {status}'
                    }
                        
        except asyncio.TimeoutError:
            return {
                'endpoint': endpoint,
                'status': 'failed',
                'reason': 'Timeout'
            }
        except aiohttp.ClientError as e:
            return {
                'endpoint': endpoint,
                'status': 'failed',
                'reason': f'Client error: {str(e)[:100]}'
            }
        except Exception as e:
            return {
                'endpoint': endpoint,
                'status': 'failed',
                'reason': f'Unexpected error: {str(e)[:100]}'
            }
        
        # This should never be reached, but just in case
        return {
            'endpoint': endpoint,
            'status': 'failed',
            'reason': 'Unknown error'
        }

    async def test_all_endpoints(self, categories: Dict[str, Any]):
        """Test all endpoints across all categories."""
        all_endpoints = []
        
        # Collect all endpoints
        for category_id, category_data in categories.items():
            endpoints = self.extract_endpoints(category_data)
            all_endpoints.extend(endpoints)
            self.results['categories'][category_id] = {
                'name': category_data.get('name', category_id),
                'endpoints': [],
                'passed': 0,
                'failed': 0,
                'skipped': 0
            }
        
        self.results['total_apis'] = sum(len(cat.get('apis', [])) for cat in categories.values())
        self.results['total_endpoints'] = len(all_endpoints)
        
        print(f"\n🔍 Testing {self.results['total_endpoints']} endpoints across {len(categories)} categories...")
        
        # Test endpoints in batches
        async with aiohttp.ClientSession() as session:
            for i, endpoint in enumerate(all_endpoints, 1):
                print(f"  [{i}/{len(all_endpoints)}] Testing {endpoint['category']}/{endpoint['api_name']}...", end=' ')
                
                result = await self.test_endpoint(session, endpoint)
                
                # Safety check for None result
                if result is None:
                    result = {
                        'endpoint': endpoint,
                        'status': 'failed',
                        'reason': 'Test returned None (unknown error)'
                    }
                
                # Update results
                category_id = endpoint['category']
                self.results['categories'][category_id]['endpoints'].append(result)
                
                if result['status'] == 'passed':
                    self.results['passed'] += 1
                    self.results['categories'][category_id]['passed'] += 1
                    print(f"✅ PASS ({result.get('status_code', 'N/A')})")
                elif result['status'] == 'failed':
                    self.results['failed'] += 1
                    self.results['categories'][category_id]['failed'] += 1
                    print(f"❌ FAIL - {result['reason']}")
                else:
                    self.results['skipped'] += 1
                    self.results['categories'][category_id]['skipped'] += 1
                    print(f"⏭️  SKIP - {result['reason']}")
                
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.2)

    def print_summary(self):
        """Print a detailed summary of results."""
        print("\n" + "="*80)
        print("📊 API VERIFICATION SUMMARY")
        print("="*80)
        print(f"\nOverall Results:")
        print(f"  Total APIs:      {self.results['total_apis']}")
        print(f"  Total Endpoints: {self.results['total_endpoints']}")
        print(f"  ✅ Passed:       {self.results['passed']} ({self.results['passed']/self.results['total_endpoints']*100:.1f}%)")
        print(f"  ❌ Failed:       {self.results['failed']} ({self.results['failed']/self.results['total_endpoints']*100:.1f}%)")
        print(f"  ⏭️  Skipped:      {self.results['skipped']} ({self.results['skipped']/self.results['total_endpoints']*100:.1f}%)")
        
        print(f"\n📁 Results by Category:")
        print("-"*80)
        
        for cat_id, cat_data in self.results['categories'].items():
            total = cat_data['passed'] + cat_data['failed'] + cat_data['skipped']
            pass_rate = cat_data['passed'] / total * 100 if total > 0 else 0
            
            status_icon = "✅" if cat_data['failed'] == 0 else "⚠️" if cat_data['passed'] > 0 else "❌"
            
            print(f"\n{status_icon} {cat_data['name']} ({cat_id})")
            print(f"   Passed: {cat_data['passed']}, Failed: {cat_data['failed']}, Skipped: {cat_data['skipped']} - {pass_rate:.1f}%")
            
            # Show failed endpoints
            if cat_data['failed'] > 0:
                print(f"   ❌ Failed endpoints:")
                for ep_result in cat_data['endpoints']:
                    if ep_result['status'] == 'failed':
                        ep = ep_result['endpoint']
                        print(f"      • {ep['api_name']}: {ep['path']}")
                        print(f"        Reason: {ep_result['reason']}")
                        print(f"        URL: {ep['url'][:80]}...")
        
        print("\n" + "="*80)
        
        return self.results

    def save_results(self, output_file: str = "api_verification_results.json"):
        """Save results to JSON file."""
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2)
        print(f"\n💾 Results saved to: {output_file}")

async def main():
    """Main entry point."""
    categories_dir = r"d:\clawduiback\clawd-backend\templates\telegram-bot-template\llm\categories"
    
    verifier = APIVerifier(categories_dir)
    
    # Load all categories
    print("📂 Loading API categories...")
    categories = verifier.load_all_categories()
    print(f"   Loaded {len(categories)} categories")
    
    # Test all endpoints
    await verifier.test_all_endpoints(categories)
    
    # Print summary
    verifier.print_summary()
    
    # Save results
    verifier.save_results()

if __name__ == "__main__":
    asyncio.run(main())
