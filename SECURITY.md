# Security policy

## Sensitive data

Conversation archives, generated reports, browser session access, API keys, and tool outputs can all contain confidential information. Keep them out of source control and issue attachments.

## Reporting a vulnerability

Do not publish working exploit details, real account data, session cookies, access tokens, or private archives in a public issue. Use GitHub's private vulnerability reporting feature if it is enabled for the repository; otherwise contact the maintainer through a private channel that the maintainer has explicitly published.

## Scope and limitations

The browser userscript runs in the context of supported authenticated chat sites and uses the site's session to retrieve conversation data. A malicious or compromised userscript build could access sensitive page data. Install only a build you trust, inspect updates, and avoid installing modified copies from unknown sources.

Optional remote AI analysis sends selected conversation excerpts to the configured provider. This is a deliberate user configuration, not an offline operation. Local model runtimes reduce third-party transfer but still require securing the local host and its access controls.
