'use client';

/**
 * GroupCard — presentational topic-group row (ADR-001).
 * Join/leave is a callback owned by the view's hook.
 */

import type { SocialGroup } from '@/lib/social';
import { pickText } from '@/lib/localize';

interface GroupCardProps {
  group: SocialGroup;
  locale: string;
  joinLabel: string;
  leaveLabel: string;
  joiningLabel: string;
  leavingLabel: string;
  membersLabel: string;
  visitLabel: string;
  href: string;
  busy: boolean;
  onToggleJoin: () => void;
}

export function GroupCard({
  group,
  locale,
  joinLabel,
  leaveLabel,
  joiningLabel,
  leavingLabel,
  membersLabel,
  visitLabel,
  href,
  busy,
  onToggleJoin,
}: GroupCardProps) {
  const joined = Boolean(group.joined);
  const name = pickText(group.name, locale);
  const description = pickText(group.description, locale);
  return (
    <article className="soc-group">
      <div className="soc-group-main">
        <h3 className="soc-group-name">
          <a href={href}>{name}</a>
        </h3>
        {description && <p className="soc-group-desc">{description}</p>}
        <span className="soc-group-members">
          {group.member_count} {membersLabel}
        </span>
      </div>
      <div className="soc-group-actions">
        <a className="soc-btn soc-btn-ghost" href={href}>
          {visitLabel}
        </a>
        <button
          type="button"
          className={`soc-btn${joined ? ' soc-btn-ghost' : ' soc-btn-primary'}`}
          onClick={onToggleJoin}
          disabled={busy}
          aria-pressed={joined}
        >
          {busy ? (joined ? leavingLabel : joiningLabel) : joined ? leaveLabel : joinLabel}
        </button>
      </div>
    </article>
  );
}
