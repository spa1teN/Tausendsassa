# Privacy Policy

**Last Updated:** July 19, 2026

This Privacy Policy describes how Tausendsassa Discord Bot ("Bot") and its
associated web admin panel ("Web Panel") collect, use, and protect your
information.

## 1. Information We Collect

### Automatically Collected Data
- **Discord User IDs**: To identify users for map pins, cooldown tracking, and
  OAuth2 login.
- **Discord Server IDs**: To maintain server-specific configurations.
- **Discord Channel IDs**: To post feeds, calendar summaries, and maps in
  configured channels.
- **Interaction Data**: Slash command usage, button clicks, and component
  interactions for functionality and analytics.

### User-Provided Data
- **RSS/Atom Feed URLs**: Feed sources you configure for monitoring.
- **Location Information**: Geographic locations you voluntarily share via the
  `/map` pin feature, including geocoded coordinates from Nominatim
  (OpenStreetMap).
- **Map Customizations**: Pin colors and map region preferences.
- **Calendar URLs**: iCal/ICS calendar feeds you configure for event
  synchronization.
- **Calendar Filters**: Blacklist and whitelist terms for event filtering.
- **Discord Event Data**: Event titles, descriptions, and timing from iCal
  feeds.
- **Server Settings**: Feed configurations, calendar settings, timezone
  preferences, moderation settings, and webhook URLs.
- **Feedback Submissions**: Messages, subject category, and anonymity
  preference sent via the `/feedback` slash command.

### OAuth2 Data (Web Panel)
- Discord username, avatar hash, and list of guilds where you have
  administrative permissions (for access control only — not stored
  persistently).

### Technical Data
- **Log Data**: Error logs, system performance metrics, and operational status.
- **Cache Data**: HTTP cache for feed requests (ETag, Last-Modified), webhook
  cache, and map image cache (all automatically managed).
- **Analytics**: Anonymous page-view, map-view, slash-command, and
  component-interaction counters aggregated hourly. No per-user analytics are
  stored.

## 2. How We Use Your Information

### Core Functionality
- **RSS/Atom Feeds**: Monitor and post feed updates to configured channels via
  Discord webhooks.
- **Reddit & Bluesky Feeds**: Fetch and display posts from Reddit (via public
  RSS and authenticated JSON API) and Bluesky (via AT Protocol).
- **RedGifs Media**: Resolve RedGifs links to downloadable media for inline
  display (guild-gated).
- **Interactive Maps**: Display user-set location pins on rendered maps,
  accessible via Discord CV2 messages, the 3D globe page, and Discord
  Activities.
- **Calendar Integration**: Fetch iCal data, manage Discord event lifecycle
  (create/start/end automatically), and post weekly summaries.
- **Moderation Logging**: Record join, leave, kick, ban, unban, and timeout
  events for server admins.
- **Feedback System**: Collect and manage user-submitted feedback with
  per-guild status tracking.
- **System Operation**: Maintain bot functionality, monitor health, and
  troubleshoot issues.

### Data Processing
- All data processing and storage occurs on the host server (PostgreSQL
  database, local filesystem).
- No data is sold, traded, or rented to third parties.
- External service calls are limited to what each feature requires — see
  Section 4.

## 3. Data Storage and Security

### Storage
- **Primary storage**: PostgreSQL database (hosted on the same server).
- **Map cache**: PNG images in `data/map_cache/` and per-guild directories.
- **Logs**: Rotating log files with automatic cleanup.
- **Backups**: Automated `pg_dump` backups stored locally, oldest removed after
  7 days.

### Data Security
- Access to the database and server restricted to the bot operator.
- Database credentials never exposed to the Discord client or web visitors.
- Web Panel sessions use server-side signed cookies (itsdangerous) with 7-day
  expiry.
- Map pins and GeoJSON endpoints require Discord OAuth2 login or a shared
  access token — they are not publicly accessible.
- Regular automated backups of all configuration and user data.

### Data Retention
- **Server Configuration**: Retained while the bot is active on the server.
- **Location Data (Map Pins)**: Stored until you remove your pin or leave the
  server (one pin per user per guild).
- **Calendar Data**: Stored until the calendar is removed by an admin.
- **Discord Events**: Stored while active; cleaned up when events are deleted.
- **Log Data**: Rotated daily with limited retention.
- **Cache Data**: Managed automatically with size limits and periodic cleanup.
- **Analytics**: Hourly rollups retained indefinitely (aggregate counts only,
  no user-level data).
- **Feedback**: Retained until the bot leaves the server; can be archived by
  admins.

## 4. Data Sharing and Third Parties

### No Data Sales
We do not sell, trade, or rent your personal information to third parties.

### External Services
- **Discord API**: All bot functionality depends on Discord's API. User IDs,
  server IDs, and message content are transmitted to Discord as part of normal
  bot operation.
- **Nominatim / OpenStreetMap**: Location queries from map pins are sent to
  OSM's geocoding service to resolve coordinates.
- **iCal Hosts**: Calendar URLs (Google Calendar, Outlook, etc.) are fetched to
  retrieve event data.
- **Reddit**: Feed polling uses Reddit's public RSS endpoints and authenticated
  JSON API (gallery resolution) with a stored browser cookie.
- **Bluesky**: Feed polling uses the Bluesky AT Protocol public API.
- **RedGifs**: Media resolution uses the RedGifs API v2 for HD media download.
- **CDN / Basemaps**: The 3D globe pages load map tiles from CARTO CDN and
  MapLibre.

### Visibility
- **Map pins** are visible to all members of the server where they were set,
  and to authenticated users of the Web Panel with access to that server's map.
- **RSS feed and calendar configurations** are visible to server admins via the
  Web Panel and Discord dashboards.
- **Calendar events and summaries** are visible to all server members in
  configured channels.
- **Moderation logs** are visible to server admins via the Web Panel.

## 5. Your Rights and Choices

### Data Control
- **Remove Pins**: Delete your location data using the `/map` command or the
  pin options menu.
- **Remove Calendars**: Server admins can remove calendars via Discord commands
  or the Web Panel.
- **Leave Servers**: Your map pin is automatically removed when you leave or
  are removed from a server.
- **Feedback**: Submitted feedback can be archived by server admins. The
  `/feedback` command includes an anonymous-submission option.
- **Contact Admins**: For data deletion requests, contact a server
  administrator or the bot operator.

### Access
- View your current map pin via the `/map` command or the 3D globe page.
- Update your pin location at any time (subject to per-guild cooldown limits).
- Server admins can view and manage all server data via the Web Panel.

## 6. Cookies

The Web Panel uses a single session cookie (`session`) set by Starlette
SessionMiddleware. It contains a signed, opaque session identifier — no
personal data is stored in the cookie itself. The cookie expires after 7 days
of inactivity. No tracking or advertising cookies are used.

## 7. Data Processing Legal Basis

We process your data based on:
- **Legitimate Interest**: Bot functionality and system operation.
- **Consent**: Voluntary participation in map features and feedback submission.
- **Contract Performance**: Providing requested bot services to server admins.

## 8. International Data Transfers

- The bot operates on a server located in Germany.
- Discord services operate globally with their own data protection measures.
- Geocoding queries to OpenStreetMap may involve international data
  transmission.
- Feed polling fetches data from servers worldwide based on configured URLs.

## 9. Children's Privacy

This bot is not intended for children under 13. We do not knowingly collect
information from children under 13. If you believe a child has provided
information, please contact us.

## 10. Changes to This Policy

We may update this Privacy Policy periodically. Changes will be posted at
`/privacy` on the Web Panel with an updated date. Continued use constitutes
acceptance of changes.

## 11. Contact Information

For privacy-related questions or requests:
- Contact the bot operator via Discord: `spa1teN`
- Use the `/feedback` slash command in any server where the bot is active
- Review the bot documentation and data management commands
