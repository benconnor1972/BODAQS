#pragma once
#include <WebServer.h>

// Registers /files, /download, /delete, /delete_multi, /download_zip
void registerFileRoutes(WebServer& srv);
