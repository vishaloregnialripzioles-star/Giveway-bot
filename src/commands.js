const { SlashCommandBuilder } = require("discord.js");

const pingCommand = new SlashCommandBuilder()
  .setName("ping")
  .setDescription("Check whether the bot is online and responding");

const commandData = [pingCommand.toJSON()];

module.exports = { commandData };
