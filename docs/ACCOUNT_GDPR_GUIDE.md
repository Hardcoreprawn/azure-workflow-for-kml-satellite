---
description: "GDPR compliance and user data rights for account management."
---

# Account Management & GDPR Compliance Guide

## Overview

Canopex account management is built on GDPR-first principles. Users have full control over their data:
- **Access**: View all personal data (GET /api/user)
- **Rectification**: Update display name and account details (PATCH /api/user/profile)
- **Erasure**: Delete all account data and associated content (DELETE /api/user)
- **Portability**: Export personal data in structured format (JSON)
- **Restriction**: Suspend account without deletion (future)

---

## User Rights & Implementation

### 1. Right to Access (GDPR Article 15)

**What it means**: Users can request and view all personal data held about them.

**How Canopex implements it**:

```bash
GET /api/user
Authorization: Bearer {JWT}
```

**Response** (authenticated user):
```json
{
  "user_id": "u-xyz123",
  "email": "user@example.com",
  "display_name": "Alice Example",
  "created_at": "2026-01-01T00:00:00Z",
  "last_login": "2026-05-15T14:30:00Z",
  "org_id": "org-abc456",
  "org_role": "owner"
}
```

**Data included**:
- User ID, email, display name
- Account creation & last login timestamps
- Organization membership (if any) and role
- Does NOT include internal fields prefixed with `_` (e.g., `_cosmos_meta`)

**Endpoint contract**:
- **Status 200**: Success, return user document (minus internal fields)
- **Status 404**: User not found (account deleted or invalid)
- **Status 503**: Cosmos DB unavailable

**User action**: User visits Account → Profile, data auto-populates from this endpoint.

---

### 2. Right to Rectification (GDPR Article 16)

**What it means**: Users can correct inaccurate personal data.

**How Canopex implements it**:

```bash
PATCH /api/user/profile
Authorization: Bearer {JWT}
Content-Type: application/json

{
  "display_name": "Alice Updated"
}
```

**Constraints**:
- `display_name` is required, non-empty, max 200 characters
- Only the profile owner can modify their own profile
- Email is NOT editable (primary identifier; contact support to change)

**Endpoint contract**:
- **Status 200**: Success, return updated user document
- **Status 400**: Validation error (empty name, exceeds 200 chars, invalid format)
- **Status 404**: User not found
- **Status 503**: Cosmos DB unavailable

**User action**: User visits Account → Profile, edits display name, clicks Save. Form validates, calls PATCH, updates display in real-time.

**Audit trail**: Update timestamp is stored server-side (future: changelog for compliance audits).

---

### 3. Right to Erasure (GDPR Article 17) — "Right to be Forgotten"

**What it means**: Users can request deletion of all personal data. Exception: data required for legal/contractual reasons.

**How Canopex implements it**:

```bash
DELETE /api/user?transfer_to=u-recipient123
Authorization: Bearer {JWT}
```

`transfer_to` (optional query parameter): user_id to transfer org ownership to.
Required if the authenticated user is the sole owner of any organisation.

**Deletion scope** (cascading):

1. **User document** → Deleted entirely
2. **Org memberships** → User removed from all organizations
3. **Org ownership** → If user is sole owner, ownership transferred (if `transfer_to` provided) or deletion blocked with 400
4. **Analyses & runs** → Marked for deletion (soft-delete, cascading audit log cleanup follows)
5. **Invites** → Pending invites issued by user are revoked; invites TO user are deleted
6. **Billing records** → Retained for 7 years per tax law (CANNOT delete; anonymized in GDPR export)

**Ownership transfer rules**:
- If user is **sole owner** of an org and `transfer_to` is not provided → **400 Bad Request**
- If user is **sole owner** and `transfer_to` is provided:
  - `transfer_to` user must already be an org member
  - Ownership transferred to recipient
  - Original user removed from org
- If user is **not owner** (member only) → No transfer needed; removal succeeds

**Endpoint contract**:
- **Status 204**: Success (no content), user deleted
- **Status 400**: Validation error (invalid transfer_to, transfer_to is not org member, sole owner without transfer)
- **Status 404**: User not found
- **Status 503**: Cosmos DB unavailable

**User action**: User visits Account → Account Settings → Delete Account (red button). Form requires confirmation + optional transfer_to. On submit:
1. Modal confirms action: "This will permanently delete your account, all invites, and all associated data."
2. If user is org owner, form requires "Transfer ownership to:" field (member selector)
3. On confirm, DELETE /api/user is called
4. On success, session ends, user redirected to home page

**Why `transfer_to` is required for sole owners**:
- Org data is not deleted; only user is deleted
- If sole owner is deleted without transfer, org becomes orphaned
- Law requires delegation of responsibility; transfer ensures continuity

---

### 4. Right to Data Portability (GDPR Article 20)

**What it means**: Users can obtain a copy of their personal data in a structured, machine-readable format.

**How Canopex implements it**:

```bash
GET /api/user
Authorization: Bearer {JWT}
```

**Format**: JSON (structured, portable to any system)

**Portable data**:
- User profile (ID, email, display name, timestamps)
- Organization membership (org name, role, member list)
- Analysis metadata (IDs, names, creation dates — NOT raster imagery, as that is separate)

**NOT portable** (license/contractual restrictions):
- Satellite imagery (licensed from providers; cannot be exported/redistributed)
- Model outputs (derivative; export via analysis export endpoint instead)
- Billing records (aggregated, not personal; retained for 7 years)

**User action**: User visits Account → Privacy, clicks "Export My Data". Response is JSON download with all personal data in one file.

**Future enhancement**: Provide CSV option for accessibility.

---

### 5. Right to Restriction (GDPR Article 18) — Future

**Status**: Not yet implemented. Planned for Slice 8B.

**What it means**: Users can ask to suspend their account without deletion.

**Planned flow**:
- Account restricted: login disabled, data not deleted
- User can unrestrict anytime within 90 days
- After 90 days, restricted account is auto-deleted

---

## Data Retention & Minimization

### Personal Data Retained

| Data | Retention | Reason |
|------|-----------|--------|
| User profile (ID, email, display_name) | Until deletion | Service operation (auth, billing, communication) |
| Account creation & login timestamps | Until deletion | Audit trail, fraud detection |
| Org membership & role | Until user leaves/deletion | Service operation |
| Invites (pending & accepted) | Until accepted or 90 days | Anti-spam, audit trail |
| Billing records | 7 years | Tax law (EU VAT Directive 2006/112/EC) |
| Runs & analyses metadata | Until deletion | Service operation, compliance evidence |
| Satellite imagery inputs | Until analysis deleted | On-demand user request |

### Data NOT Retained

- Server logs: Rotated daily; debug logs deleted after 7 days (future: configurable)
- Session tokens: Cleared on logout; TTL = 24 hours
- Temporary files: Deleted on upload completion
- IP addresses: Not logged (except for security anomalies, retained 30 days)

---

## User Rights Workflow (Complete Journey)

### User: "I want to see my data"
→ Visit Account → Profile → Auto-loads from GET /api/user
→ Email, display name, org membership shown
→ User can export data as JSON

### User: "I want to change my name"
→ Visit Account → Profile → Edit display name → Click Save
→ PATCH /api/user/profile validates & updates
→ Real-time confirmation: "Profile updated"

### User: "I want to delete my account"
→ Visit Account → Account Settings → Delete Account (red button)
→ If org owner: Modal shows "Transfer ownership to:" field, requires selection
→ If org member: Modal shows "Delete account (no transfer needed)"
→ Confirm → DELETE /api/user called
→ On success: Logged out, redirected to home page
→ Opt-in email: "Your account has been deleted. All personal data removed."

### User: "I want to delete my account, but I own an org"
→ Visit Account → Account Settings → Delete Account
→ Modal shows: "You own Organization XYZ. Transfer ownership to a member before deleting."
→ Form requires: Select member → Confirm
→ DELETE /api/user?transfer_to=u-member-id
→ Ownership transferred; user removed; account deleted

---

## Data Protection Measures

### Access Control
- **Authentication**: JWT (HS256) with email claim; signed with INVITE_TOKEN_SECRET
- **Authorization**: `@require_auth` wrapper enforces user identity; users can only access/modify own data
- **Organization gates**: Users can only access orgs they belong to (verified in service layer)

### Data Security
- **Encryption at rest**: Cosmos DB encryption (Azure platform feature)
- **Encryption in transit**: HTTPS/TLS 1.2+ for all API calls
- **No plaintext storage**: Passwords managed by Azure Entra ID (CIAM); Canopex never stores passwords
- **Secrets management**: INVITE_TOKEN_SECRET in Key Vault (not in code/logs)

### Audit & Compliance
- **Deletion audit**: When user is deleted, service logs the deletion timestamp & trigger
- **GDPR fields**: User records include creation timestamp for "how long have you held data?" queries
- **Right to access logs**: GET /api/user returns all fields user can see (no hidden fields)

---

## Compliance Checklist

- ✅ **Consent**: Users consent to account creation & org membership via app usage
- ✅ **Transparency**: Privacy policy visible on website; account page shows what data is held
- ✅ **Access**: GET /api/user returns all personal data (Article 15)
- ✅ **Rectification**: PATCH /api/user/profile allows updates (Article 16)
- ✅ **Erasure**: DELETE /api/user removes all personal data; cascades to org removal (Article 17)
- ✅ **Portability**: GET /api/user returns JSON; portable to any system (Article 20)
- ✅ **Retention**: Data only retained while necessary; billing records retained per legal requirement
- ✅ **Documentation**: This document + code comments explain GDPR compliance per Article 5
- ✅ **Breach notification** (future): Automated alerts to DPO on data access anomalies

---

## Common Questions

**Q: What if I delete my account but my co-owner still uses the org?**
A: If you own an org with other members, you must transfer ownership to another member (or delete the entire org) before deleting your account. This ensures no orphaned organizations. The org continues under new leadership.

**Q: Can Canopex staff delete my data on my behalf?**
A: No. Only you can delete your account via the DELETE /api/user endpoint. This ensures accountability and prevents unauthorized erasure.

**Q: What happens to my analyses after I delete my account?**
A: Your personal profile is deleted, but analyses and runs you created are marked for deletion. The system respects the "right to be forgotten" by cascading deletion through associated data. Imagery you uploaded is also deleted (unless org members have active analyses referencing it—those are preserved as a fallback).

**Q: Can I recover a deleted account?**
A: No. Deletion is permanent and irreversible after 30 days. Contact support within 30 days of deletion for emergency recovery options.

**Q: How long are my invites kept?**
A: Pending invites expire after 7 days. Accepted invites are archived. Revoked or expired invites are deleted after 90 days to allow GDPR cleanup.

**Q: Is my billing data deleted when I delete my account?**
A: No. Billing records are retained for 7 years per EU tax law (VAT Directive 2006/112/EC). However, they are anonymized: your name is removed, email is anonymized to a hash, and only aggregate usage is retained. This complies with GDPR Article 6 (legitimate interest: tax compliance).

---

## Documentation References

- **GDPR regulations**: https://gdpr-info.eu/
- **User Rights in Detail**: https://gdpr-info.eu/chapters/rights-of-the-data-subject/
- **Canopex Privacy Policy**: See website footer
- **Canopex Security Policy**: [SECURITY.md](../SECURITY.md)
- **Data Retention Policy**: This document + [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md)

---

## Implementation Checklist for Future Slices

- [ ] **Slice 8A (COMPLETED)**: Core user rights (access, rectification, erasure, portability)
- [ ] **Slice 8B**: Right to restriction (account suspension without deletion)
- [ ] **Slice 8C**: Data subject rights audit (logging who accessed what user data)
- [ ] **Slice 8D**: Automated data retention cleanup (delete aged temporary files)
- [ ] **Slice 8E**: GDPR impact assessment (Data Protection Impact Assessment)
- [ ] **Slice 8F**: Breach notification automation (alert DPO on anomalies)

---

**Last updated**: May 16, 2026
**Status**: Slice 8 complete (E2E tests + GDPR documentation)
**Next review**: After privacy policy review with legal team
