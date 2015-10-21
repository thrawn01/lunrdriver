import socket


def resolve_hostname(target_portal):
    """
    Try to lookup the ip of the of the hostname in target_portal.

    Thin wrapper around the socket module's gethostbyname function.

    :param target_portal: a string, in the format "hostname:port"

    :returns: "host_ip:port" or "hostname:port" if lookup fails
    """
    hostname, port = target_portal.split(':')
    try:
        host_ip = socket.gethostbyname(hostname)
    except socket.gaierror:
        # this host can't resolve, just pass the name through
        return target_portal
    return ':'.join((host_ip, port))


def initialize_connection(client, volume_id, connector):
    ip = connector.get('ip', None)
    resp = client.exports.create(volume_id, ip=ip)
    if '.' in resp.body['target_portal']:
        target_portal = resp.body['target_portal']
    else:
        # iscsiadm has trouble with /etc/hosts entries
        target_portal = resolve_hostname(resp.body['target_portal'])
    return {
        'driver_volume_type': 'iscsi',
        'data': {
            'target_discovered': False,
            'target_iqn': resp.body['target_name'],
            'target_portal': target_portal,
            'volume_id': volume_id,
        }
    }


