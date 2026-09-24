/**
 * ecd-client.js — 阿里云 ECD SDK 最小封装（仅需 RunCommand + DescribeInvocations）
 *
 * 作为 optionalDependency 存在：base 安装零原生依赖；需要 host-pull 时手动补装。
 */
'use strict';

let ECDClient20200930, Config, RunCommandRequest, DescribeInvocationsRequest;
try {
  const ECD = require('@alicloud/ecd20200930');
  const OpenApi = require('@alicloud/openapi-core');
  ECDClient20200930 = ECD.default;
  RunCommandRequest = ECD.RunCommandRequest;
  DescribeInvocationsRequest = ECD.DescribeInvocationsRequest;
  Config = OpenApi.$OpenApiUtil.Config;
} catch (e) {
  throw new Error('ECD SDK not installed (@alicloud/ecd20200930 + @alicloud/openapi-core)');
}

class ECDClient {
  constructor(accessKeyId, accessKeySecret, region) {
    this.region = region;
    this.client = new ECDClient20200930(
      new Config({
        accessKeyId,
        accessKeySecret,
        endpoint: `ecd.${region}.aliyuncs.com`,
        regionId: region,
      })
    );
  }

  async runCommand(desktopId, commandContent, opts = {}) {
    const req = new RunCommandRequest({
      regionId: this.region,
      type: opts.type || 'RunPowerShellScript',
      commandContent,
      desktopId: [desktopId],
      timeout: opts.timeout || 120,
      contentEncoding: 'PlainText',
    });
    return this.client.runCommand(req);
  }

  async getInvocationResult(invokeId) {
    const req = new DescribeInvocationsRequest({
      regionId: this.region,
      invokeId,
      includeOutput: true,
    });
    return this.client.describeInvocations(req);
  }
}

module.exports = { ECDClient };
