# Terms of Service

**Last Updated:** July 19, 2026

Welcome to Tausendsassa ("Bot"). These Terms of Service ("Terms") govern your
use of the Bot, its associated web admin panel ("Web Panel"), and all related
services. By using the Bot, you agree to these Terms. If you do not agree, do
not use the Bot.

## 1. Services Provided

The Bot provides the following services on Discord:

1. **RSS/Atom Feed Integration**: Monitors and posts feed updates to configured
   channels, supporting standard RSS, Reddit, Bluesky, and other sources.
2. **Interactive Map System**: Allows users to pin locations on world, regional,
   and local maps with a 3D globe view and Discord Activity integration.
3. **Calendar Integration**: Synchronizes iCal/ICS calendars with Discord,
   automatically managing event creation, start, and end, plus weekly summaries.
4. **Moderation Logging**: Records member join/leave events and moderation
   actions (kick, ban, unban, timeout) with moderator and reason tracking.
5. **Feedback System**: Per-server feedback collection with status management.
6. **Web Admin Panel**: Browser-based dashboard at
   `tausendsassa.casparsadenius.de` where server admins can manage feeds,
   calendars, maps, moderation settings, and feedback.

## 2. User Responsibilities

1. **Server Management**: You are responsible for inviting and configuring the
   Bot in your servers.
2. **Permissions**: Ensure the Bot has the permissions it needs (send messages,
   manage webhooks, create events, embed links, attach files, etc.).
3. **Content Compliance**: Do not use the Bot to distribute illegal content,
   spam, or violate Discord's Terms of Service or Community Guidelines.
4. **Location Data**: When using map features, only share location information
   you are comfortable making visible to server members and authenticated Web
   Panel users.
5. **Feed Sources**: You are responsible for the content of RSS feeds, Reddit
   subreddits/users, and Bluesky accounts you configure. The Bot does not
   endorse or moderate third-party feed content.
6. **Calendar Data**: When configuring iCal calendars, ensure you have
   permission to sync and display the events. Calendar events will be visible
   to all server members in configured channels, and Discord events will be
   automatically started and ended based on calendar timing.
7. **Calendar Configuration**: Use filtering features (blacklist/whitelist)
   responsibly to ensure appropriate content.
8. **Web Panel Access**: Access to the Web Panel is limited to Discord users
   with administrator permissions on servers where the Bot is active. Do not
   share session URLs or attempt to access servers you do not administer.

## 3. Third-Party Content

The Bot republishes content from external sources configured by server admins
(RSS/Atom feeds, Reddit, Bluesky, iCal feeds). The Bot operator is not
responsible for the content, accuracy, or availability of third-party feeds.
Server admins are responsible for the feeds they configure and should ensure
they comply with the source's terms of service.

## 4. Data Collection and Use

Data collection and processing is described in full in the [Privacy
Policy](/privacy). By using the Bot, you consent to the data practices
described there. Key points:

- User IDs, server IDs, and channel IDs are stored for functionality.
- Map pin locations are stored until removed by the user or on leaving the
  server.
- No personal data is sold or shared with third parties beyond what each
  feature requires (Discord API, OpenStreetMap geocoding, feed sources).
- The Web Panel uses a session cookie for authentication; no tracking cookies
  are used.

## 5. Service Availability

1. The Bot is provided "as is" with no guarantees of uptime or availability.
2. Features may be temporarily unavailable due to maintenance, Discord API
   changes, or technical issues.
3. We reserve the right to modify or discontinue features with reasonable
   notice.
4. The Bot operator may terminate service to any server at any time for
   violations of these Terms.

## 6. Prohibited Uses

1. Using the Bot to violate Discord's Terms of Service or Community Guidelines.
2. Attempting to exploit, hack, abuse, or reverse-engineer the Bot, its API
   servers, or the Web Panel.
3. Using the Bot for illegal activities, harassment, or distribution of
   prohibited content.
4. Sharing malicious or inappropriate content through configured RSS feeds or
   map interactions.
5. Unauthorized access to the Web Panel or internal APIs.

## 7. Limitation of Liability

1. The Bot is provided without warranty of any kind, express or implied.
2. The developers and operator are not liable for any damages arising from the
   use or inability to use the Bot or its services.
3. Users and server admins assume all risks associated with using the Bot's
   features, including reliance on third-party content and services.
4. The Bot operator is not responsible for data loss, though regular
   automated backups are maintained.

## 8. Changes to These Terms

These Terms may be updated at any time. Changes will be posted at `/terms` on
the Web Panel with an updated date. Continued use of the Bot after changes
constitutes acceptance of the updated Terms.

## 9. Termination

Server admins may remove the Bot from their server at any time. The Bot
operator may revoke access to the Bot or Web Panel for violations of these
Terms. Upon bot removal from a server, that server's data (feeds, calendars,
map pins, logs) is no longer accessible but may persist in database backups.

## 10. Contact

For questions about these Terms or to report violations:
- Discord: `spa1teN`
- Use the `/feedback` slash command in any server where the Bot is active
