import xml.etree.ElementTree as ET
import sys

ns = {}
tree = ET.parse(r"Simba Validador.iBot")
root = tree.getroot()
xsi = "{http://www.w3.org/2001/XMLSchema-instance}"

def local(tag):
    return tag.split('}')[-1]

# Find all AutxActivity under Activities
activities_root = root.find("Activities")
activities = activities_root.findall("AutxActivity")

def get_text(el, tag):
    c = el.find(tag)
    return c.text if c is not None else None

for act in activities:
    act_id = get_text(act, "ID")
    name = get_text(act, "Name")
    items_el = act.find("Items")
    if items_el is None:
        continue
    design_items = items_el.findall("DesignItem")

    nodes = {}  # id -> dict(type, label, ports: {portname: portid})
    port_owner = {}  # port id -> (node id, port name)
    connections = []  # (src_comp, src_port, sink_comp, sink_port, kind)

    def register_port(node_id, port_el, pname):
        if port_el is None:
            return
        pid = get_text(port_el, "ID")
        if pid:
            port_owner[pid] = (node_id, pname)

    for di in design_items:
        t = di.attrib.get(xsi+"type")
        did = get_text(di, "ID")
        if t in ("AutxControlConnection", "AutxDataConnection"):
            src_c = get_text(di, "SourceComponentID")
            src_p = get_text(di, "SourcePortID")
            sink_c = get_text(di, "SinkComponentID")
            sink_p = get_text(di, "SinkPortID")
            connections.append((src_c, src_p, sink_c, sink_p, t))
            continue
        # label: try <Name> direct child (action name) else type
        label = get_text(di, "Name")
        if not label:
            label = t
        nodes[did] = {"type": t, "label": label, "ports": {}}
        # register known control ports
        for pname in ["ControlIn","ControlOut","ControlYes","ControlNo","ElsePort"]:
            register_port(did, di.find(pname), pname)
        # Decision Yes/No might be named differently; also check generic ControlOut inside Options for Switch
        opts = di.find("Options")
        if opts is not None:
            for i, opt in enumerate(opts.findall("SwitchOption")):
                p = opt.find("Port")
                if p is not None:
                    pid = get_text(p,"ID")
                    dp = opt.find("DataPort")
                    optlabel = get_text(dp, "StaticValue") if dp is not None else f"Option_{i}"
                    if pid:
                        port_owner[pid] = (did, f"CASE:{optlabel}")

    print(f"\n=== ACTIVITY: {name} ({act_id}) — {len(nodes)} nodes, {len(connections)} connections ===")
    # Build adjacency from control connections only, using port_owner to label branch
    adj = {}
    for src_c, src_p, sink_c, sink_p, kind in connections:
        if kind != "AutxControlConnection":
            continue
        branch = None
        if src_p in port_owner:
            branch = port_owner[src_p][1]
        adj.setdefault(src_c, []).append((branch, sink_c))

    # find EntryPoint node id
    entry_ids = [nid for nid,v in nodes.items() if v["type"]=="EntryPoint"]
    print("Entry points:", entry_ids)
    for eid in entry_ids:
        def walk(nid, depth, branch_label, path):
            indent = "  "*depth
            info = nodes.get(nid)
            if info is None:
                print(f"{indent}-> [unknown node {nid}]")
                return
            tag = f" ({branch_label})" if branch_label else ""
            if nid in path:
                print(f"{indent}{info['type']}: {info['label']}{tag}  <-- BACK-EDGE (loop to earlier node, stop)")
                return
            print(f"{indent}{info['type']}: {info['label']}{tag}")
            newpath = path | {nid}
            outs = adj.get(nid, [])
            if not outs:
                return
            for branch, nxt in outs:
                walk(nxt, depth+1, branch, newpath)
        walk(eid, 0, None, frozenset())
