import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { getProfiles, syncRemovalWarning, syncSummary } from "@/lib/data/profiles";
import { formatKst } from "@/lib/display/time";
import { runErrorMessage } from "@/lib/display/errors";
import { workerStatus } from "@/lib/display/worker";
import { ProfileForm } from "./profile-form";
import { SyncButton } from "./sync-button";

const workerLabels = { online: "연결됨", stale: "응답 지연", not_serving: "담당 워커 없음" };
export default async function ProfilesPage() {
  const { profiles, heartbeats } = await getProfiles();
  const now = new Date();
  return <div className="space-y-6">
    <h1 className="text-2xl font-bold">프로필</h1>
    <ProfileForm />
    {profiles.length === 0 && <p>등록된 프로필이 없습니다.</p>}
    <div className="grid gap-4 md:grid-cols-2">
      {profiles.map((profile, index) => <section key={profile.id} className="space-y-3 rounded-lg border p-4">
        <h2 className="font-semibold"><Link href={`/profiles/${profile.id}/conditions`}>{profile.display_name || profile.alias}</Link></h2>
        <p className="text-sm">{profile.alias}</p>
        <Badge variant={profile.mode === "real" ? "destructive" : "secondary"}>{profile.mode === "real" ? "실전" : "모의"}</Badge>
        <p>워커: {workerLabels[workerStatus(heartbeats, profile.alias, now)]}</p>
        <p>마지막 성공: {profile.last_ok_at ? formatKst(profile.last_ok_at) : "없음"}</p>
        {profile.last_error_code && <p role="alert" className="text-destructive">{runErrorMessage(profile.last_error_code)}</p>}
        {profile.latestSync && <div className="text-sm">
          <p>최근 동기화: {formatKst(profile.latestSync.requested_at)} ({profile.latestSync.status})</p>
          <p>{syncSummary(profile.latestSync.sync_summary)}</p>
          {syncRemovalWarning(profile.latestSync.sync_summary) && <p role="alert" className="text-destructive">{syncRemovalWarning(profile.latestSync.sync_summary)}</p>}
          {profile.latestSync.error_code && <p>{runErrorMessage(profile.latestSync.error_code)}</p>}
        </div>}
        <SyncButton profileId={profile.id} refreshPage={index === 0} />
        <Link className="text-sm underline" href={`/profiles/${profile.id}/conditions`}>조건식 보기</Link>
      </section>)}
    </div>
  </div>;
}
