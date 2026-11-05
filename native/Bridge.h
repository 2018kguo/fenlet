#include <ApplicationServices/ApplicationServices.h>
#include <libproc.h>
// The WindowServer bridge used by macOS window managers to match an AX window
// to its stable CGWindowID. Every write also verifies the owning process start.
AXError _AXUIElementGetWindow(AXUIElementRef element, CGWindowID *windowID);
