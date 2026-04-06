INSERT INTO services (slug, name, url, signup_url, category, description, core_workflow, docs_url, pricing_url, contact_email, status)
VALUES
  ('agentmail-to', 'AgentMail', 'https://agentmail.to', 'https://console.agentmail.to', 'communication', 'Email inbox API for AI agents — create inboxes, send and receive email programmatically', 'Create inbox via API, receive email at generated address, send reply', 'https://docs.agentmail.to', 'https://agentmail.to/pricing', 'hello@agentmail.to', 'pending'),
  ('here-now', 'here.now', 'https://here.now', 'https://here.now', 'hosting', 'Free instant web hosting for agents — publish files and get a live URL in seconds', 'POST files to API, receive live URL at name.here.now', 'https://here.now/docs', 'https://here.now', 'support@here.now', 'pending'),
  ('moltbook', 'Moltbook', 'https://moltbook.com', 'https://moltbook.com/register', 'communication', 'Social network exclusively for AI agents — post, comment, and vote in topic-specific groups', 'Register account, create post in a submolt, comment and vote', 'https://moltbook.com/skill.md', 'https://moltbook.com', 'support@moltbook.com', 'pending'),
  ('signbee', 'Signbee', 'https://signb.ee', 'https://signb.ee/signup', 'execution', 'Document signing API for AI agents — send, sign, and verify documents with a single API call', 'Send document via API, collect recipient signature, retrieve signed PDF with certificate', 'https://signb.ee/docs', 'https://signb.ee/pricing', 'hello@signb.ee', 'pending'),
  ('browser-use', 'Browser Use', 'https://browser-use.com', 'https://browser-use.com', 'execution', 'Browser automation for AI agents — control stealth browsers via API with LLM-solvable signup', 'Solve signup math challenge, obtain API key, start and control browser session', 'https://docs.browser-use.com', 'https://browser-use.com/pricing', 'support@browser-use.com', 'pending')
ON CONFLICT (slug) DO UPDATE SET
  name = EXCLUDED.name,
  url = EXCLUDED.url,
  signup_url = EXCLUDED.signup_url,
  category = EXCLUDED.category,
  description = EXCLUDED.description,
  core_workflow = EXCLUDED.core_workflow,
  docs_url = EXCLUDED.docs_url,
  pricing_url = EXCLUDED.pricing_url,
  contact_email = EXCLUDED.contact_email;
