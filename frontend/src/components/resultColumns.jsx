import { Tag } from 'antd'

const createPortColumns = () => [
  {
    title: '端口',
    dataIndex: 'port',
    key: 'port',
    width: 80,
    sorter: (a, b) => a.port - b.port,
  },
  {
    title: '协议',
    dataIndex: 'protocol',
    key: 'protocol',
    width: 80,
  },
  {
    title: '服务',
    dataIndex: 'service',
    key: 'service',
    render: (service) => service || '-',
  },
  {
    title: '状态',
    dataIndex: 'state',
    key: 'state',
    width: 100,
    render: (state) => {
      const colorMap = {
        open: 'green',
        closed: 'default',
        filtered: 'orange',
      }
      return <Tag color={colorMap[state] || 'default'}>{state}</Tag>
    },
  },
]

export { createPortColumns }
