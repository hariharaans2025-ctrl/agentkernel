# Third-party components

The root MIT license covers original AgentKernel application code. Dependencies and retained framework/plugin files retain their own licenses and notices. Do not remove embedded license headers.

Python dependencies include Pydantic, HTTPX and Contree SDK. The hosted console uses React, Vinext, Vite, Drizzle, Lucide and Cloudflare tooling; consult the dependency lockfile and installed packages for their licenses. The Sites build helper sources retain their bundled notices.

Optional trained adapter: based on `Qwen/Qwen2.5-Coder-1.5B-Instruct` at revision `2e1fd397ee46e1388853d2af2c993145b0f1098a`. Model weights, tokenizer assets, upstream model terms and attribution remain governed by the upstream model license; the application MIT license does not override them. Base weights are downloaded separately. No NVIDIA Nemotron weights are distributed in this package; inference uses the owner's Nebius account under the provider's terms.

Synthetic fixtures are deliberately buggy test programs. They are test inputs, not production reference implementations.
