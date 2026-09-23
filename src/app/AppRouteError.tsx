import { AlertTriangle, RotateCcw } from "lucide-react";
import { isRouteErrorResponse, useRouteError } from "react-router-dom";
import "./route-error.css";

export function AppRouteError() {
  const error = useRouteError();
  const message = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : "Ein unerwarteter Fehler ist aufgetreten.";

  return <main className="route-error"><section><AlertTriangle size={30}/><p>KICKTRACK</p><h1>Ansicht konnte nicht geladen werden</h1><span>{message}</span><button type="button" onClick={() => window.location.reload()}><RotateCcw size={15}/> App neu laden</button></section></main>;
}
