import serial
import serial.tools.list_ports


def get_port_from_user() -> str:
    """
    Utility method to show the available ports on stdout and ask the user to pick one.

    Returns:
        string: The port name the user picked.
    """
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("No serial ports found.")
        exit(1)

    print("Available Serial Ports:")
    for i, p in enumerate(ports):
        print(f"  ({i}) {p.device} ({p.description})")

    selected_port_index = -1
    while not (0 <= selected_port_index < len(ports)):
        try:
            choice = input(
                f"Enter the number of the desired serial port (0-{len(ports)-1}): ")
            selected_port_index = int(choice)
        except ValueError:
            print("Invalid input. Please enter a number.")
        if not (0 <= selected_port_index < len(ports)):
            print("Invalid port number. Please choose from the list.")

    selected_port = ports[selected_port_index].device
    print(f"Selected serial port: {selected_port}")
    return selected_port
