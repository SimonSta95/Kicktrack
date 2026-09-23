import { RouterProvider } from "react-router-dom";
import { router } from "@/app/router";
import { PlayerDetailProvider } from "@/features/player-detail/PlayerDetailProvider";

export default function App() {
  return (
    <PlayerDetailProvider>
      <RouterProvider router={router} />
    </PlayerDetailProvider>
  );
}
