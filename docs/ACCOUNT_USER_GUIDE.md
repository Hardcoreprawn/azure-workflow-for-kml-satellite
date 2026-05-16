---
description: "User guide for account management, org invites, and privacy controls."
---

# Account Management User Guide

Welcome to Canopex! This guide explains how to manage your account, invite team members, and control your data privacy.

---

## Getting Started: Your Account

### View Your Profile

1. Click your account icon (top-right corner)
2. Select **Account** → **Profile**
3. Your profile information is displayed:
   - **Email**: Your login email (cannot be changed; contact support to update)
   - **Display Name**: Your public name (editable)

### Edit Your Profile

1. Go to Account → **Profile**
2. Click the **Edit** button
3. Update your **Display Name** (up to 200 characters)
4. Click **Save**
5. Your profile is updated immediately

---

## Organizations: Invite & Manage Team Members

### Create an Organization

1. Go to Account → **Organization**
2. If you don't have an org yet, click **Create Organization**
3. Enter your organization name
4. You become the **Owner** (full permissions)

### Invite Team Members

1. Go to Account → **Organization**
2. Click **Invite Member**
3. Enter their email address
4. Click **Send Invite**
5. They receive an invite link (expires in 7 days)

**Who can invite**: Only organization owners

### Accept an Invite

1. Click the invite link in your email (or check your account)
2. You'll see: "You've been invited to join [Organization Name]"
3. Click **Sign In to Accept** (if not already logged in)
4. Click **Accept Invitation**
5. You're now a member of the organization!

**Invite expiration**: If you don't accept within 7 days, the invite expires. Ask the owner to send a new one.

### View Team Members

1. Go to Account → **Organization**
2. See all members with their:
   - Name
   - Role (Owner or Member)
   - Email

### Remove a Team Member

1. Go to Account → **Organization**
2. Find the member in the list
3. Click the **Remove** button (red X)
4. Confirm removal

**Who can remove members**: Only organization owners

### Revoke a Pending Invite

1. Go to Account → **Organization**
2. Scroll to **Pending Invites**
3. Click **Revoke** next to the invite
4. The invite is cancelled; they won't be able to accept it

**Who can revoke invites**: Only organization owners

---

## Account Security & Privacy

### Change Your Password

Canopex uses **Microsoft Entra ID** for login. To change your password:

1. Go to your **Microsoft account settings** (not in Canopex)
2. Or, during login, click **Forgot Password** on the sign-in page

Canopex never stores your password—Microsoft manages it securely.

### Sign Out

1. Click your account icon (top-right)
2. Click **Sign Out**
3. You're logged out immediately

### Sign Out Everywhere (Future)

Coming soon: Sign out from all devices at once.

---

## Delete Your Account (Permanent)

### Before You Delete

⚠️ **Deletion is permanent and cannot be undone.**

When you delete your account:
- Your profile is removed
- You're removed from all organizations
- Your personal data is deleted
- If you own an organization, you must **transfer ownership** to a member first

### How to Delete Your Account

1. Go to Account → **Account Settings**
2. Scroll to the bottom
3. Click **Delete Account** (red button)
4. A confirmation dialog appears
5. **If you own an organization**:
   - Select a member to transfer ownership to
   - They will become the new owner
6. Click **Delete Permanently**
7. Your account is deleted; you're logged out

### Sole Owner Warning

If you're the **only owner** of an organization:
- You cannot delete your account without transferring ownership
- Select a member from the dropdown
- They must already be a member of the organization
- After transfer, they become the owner; you're removed

### What Gets Deleted

✅ **Deleted**:
- Your profile (email, name, account history)
- Your membership in all organizations
- Pending invites you've sent or received
- Your personal data

⚠️ **NOT deleted** (for compliance):
- Billing records (retained for tax purposes, 7 years)
- Analyses you created (may be retained if other org members use them)

---

## Your Data & Privacy Rights

### Access Your Data

Your account page shows all personal data Canopex holds about you:
- Email address
- Display name
- Account creation date
- Organization memberships and roles

### Export Your Data

1. Go to Account → **Profile**
2. Click **Export My Data**
3. A JSON file downloads with all your personal information
4. You can import this data into other services

### Delete Your Data

See "Delete Your Account" above. Deletion is the GDPR right to erasure ("right to be forgotten").

### Update Your Data

Edit your **Display Name** anytime (see "Edit Your Profile" above).

### Restrict Your Data (Future)

Coming soon: Suspend your account temporarily without deleting it.

---

## Troubleshooting

### "I can't find my Organization"

- Organizations are linked to your account. Check Account → **Organization**.
- If you don't see one, you either don't belong to an org yet, or you were removed.
- Ask your organization owner to invite you again.

### "The invite link expired"

Invites expire after 7 days. Ask your organization owner to send a new invite.

### "I'm the sole owner and can't delete my account"

You must transfer ownership to a member before deleting. Go to Account → **Account Settings** → **Delete Account**. The form will ask you to select a new owner.

### "I forgot my email"

Your email is displayed in Account → **Profile**. It's your login email and cannot be changed.

### "I want to change my email"

Contact **support@canopex.com** with your request. Due to security, we require verification before updating your email.

### "I deleted my account by mistake"

Deletion is permanent after 30 days. If you deleted within the last 30 days, contact **support@canopex.com** for emergency account recovery.

---

## Privacy & Data Protection

### What Data Do We Collect?

- **Required**: Email, display name, organization membership
- **Optional**: Profile picture, phone number (future)
- **Automatic**: Login timestamps, browser type (for security audits)

### How Do We Use Your Data?

- **Service operation**: Authentication, organization management, billing
- **Security**: Fraud detection, anomaly alerts
- **Communication**: Invite emails, password resets, notifications (opt-in)
- **Analytics**: Aggregate usage (anonymized, no personal data)

### What Data Do We NOT Collect?

- Passwords (Microsoft manages login security)
- Credit card numbers (Stripe handles payments; we don't see them)
- IP addresses (not logged, except for security incidents)
- Satellite imagery metadata (stored separately, not linked to user profile)

### Who Has Access to My Data?

- **Only you** can view your profile (via GET /api/user)
- **Organization owners** can see member list (emails, roles, names)
- **Canopex staff** can access data only in emergencies (security breach, legal order)
- **Microsoft**: Manages your authentication (sign-in) securely

### How Long Do We Keep Your Data?

| Data | Duration | Reason |
|------|----------|--------|
| Profile | Until account deleted | Service operation |
| Org membership | Until you leave/delete | Service operation |
| Invites | 7 days (pending) / 90 days (archived) | Spam prevention |
| Billing records | 7 years | Tax law |
| Login logs | 30 days | Security |

### Can I Export or Download My Data?

Yes! Click **Export My Data** in your Account → **Profile** section. You get a JSON file with:
- Email, display name, org info
- Timestamps (creation, last login)
- All personal information we hold

You can import this into any other service.

---

## Contact & Support

**Have questions?** Contact us:
- 📧 **Email**: support@canopex.com
- 🌐 **Website**: https://www.canopex.com
- 📋 **Help center**: https://help.canopex.com (coming soon)

**Privacy concerns?** Email: **privacy@canopex.com**

---

## Related Documents

- [GDPR Compliance Guide](./ACCOUNT_GDPR_GUIDE.md) — Technical details on data rights
- [Privacy Policy](../website/privacy.html) — Legal terms
- [Security Policy](../SECURITY.md) — How we protect your data
- [API Reference](./API_INTERFACE_REFERENCE.md) — For developers

---

**Last updated**: May 16, 2026
**Status**: Slice 8 complete (Full account management system live)
