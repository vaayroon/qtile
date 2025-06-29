import subprocess

def get_my_net():
    datanet = subprocess.Popen(["nmcli", "-g", "general.state",
                               "device", "show", "eth0"], stdout=subprocess.PIPE).communicate()
    datanetp = datanet[0].decode("utf-8")
    res = datanetp.split()
    datanet1 = res[0]
    datanet2 = res[1]

    if datanet2 == "(connected)":
        setdevice = ("eth0", "󰈀 ")
    else:
        setdevice = ("", "󰈂  󱛅 ")
    return setdevice

def get_my_net_ip():
    import subprocess
    grepdatanetp = "none"
    grepdatawifip = "none"

    datanete = subprocess.Popen(
        ["ip", "route", "show", "dev", "eth0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()

    if datanete[1].decode("utf-8") == "":
        datanet = subprocess.Popen(
                ["ip", "route", "show", "dev", "eth0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        grepdatanet = subprocess.Popen(
                ["grep", "linkdown"], stdin=datanet.stdout, stdout=subprocess.PIPE).communicate()
        grepdatanetp = grepdatanet[0].decode("utf-8")

    if grepdatanetp != "":
        datawifie = subprocess.Popen(
                ["ip", "route", "show", "dev", "wlan0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()

        if datawifie[1].decode("utf-8") == "":
            datawifi = subprocess.Popen(
                    ["ip", "route", "show", "dev", "wlan0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            grepdatawifi = subprocess.Popen(
                    ["grep", "linkdown"], stdin=datawifi.stdout, stdout=subprocess.PIPE).communicate()
            grepdatawifip = grepdatawifi[0].decode("utf-8")

    if grepdatanetp == "":
        setdevice = ("eth0", " ")
    elif grepdatawifip == "":
        setdevice = ("wlan0", "󱚻 ")
    else:
        setdevice = ("", "󰈂  󱛅 ")
    return setdevice