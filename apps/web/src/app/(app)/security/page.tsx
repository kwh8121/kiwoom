import { EnrollForm } from "./enroll-form";

export default function SecurityPage() {
  return (
    <section className="max-w-xl space-y-4">
      <h1 className="text-2xl font-bold">보안</h1>
      <h2 className="text-lg font-semibold">인증 앱(TOTP)</h2>
      <p className="text-sm">
        인증 앱을 등록하면 비밀번호만으로는 데이터를 열 수 없습니다. 등록 전까지는 지금과 동일하게 동작합니다.
      </p>
      <EnrollForm />
    </section>
  );
}
