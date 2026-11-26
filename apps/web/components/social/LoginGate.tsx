'use client';

/**
 * LoginGate — login-required state for the social surfaces (Phase 10).
 *
 * The community endpoints (groups, feed, post detail, comments) all
 * require auth, so an unauthenticated guest is shown this gate instead of
 * a 401 error state — the same pattern the learn dashboard uses. Presentational
 * only (ADR-001): the auth decision is made by the view's hook.
 */

import Link from 'next/link';
import type { SocialLabels } from './labels';

interface LoginGateProps {
  locale: string;
  labels: SocialLabels;
}

export function LoginGate({ locale, labels }: LoginGateProps) {
  return (
    <div className="page-wrap">
      <div className="soc-gate">
        <h2>{labels.loginRequiredTitle}</h2>
        <p>{labels.loginHint}</p>
        <Link className="soc-btn soc-btn-primary" href={`/${locale}/login`}>
          {labels.loginCta}
        </Link>
      </div>
    </div>
  );
}
