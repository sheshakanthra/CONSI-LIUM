import { redirect } from "next/navigation";

// The root path currently has no landing content — send visitors straight to
// the placeholder dashboard. Replaced with a real marketing/home page later.
export default function Home() {
  redirect("/dashboard");
}
